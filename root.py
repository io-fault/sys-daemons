"""
# Root daemon process for service management and scheduled processes.

# &.root provides the primary support for &.bin.rootd which manages a set of daemons,

# Multiple instances of rootd may exist, but usually only one per-user is desired.
# The (system/home)`.fault` directory is used by default, but can be adjusted by a command
# line parameter. The daemon directory supplies all the necessary configuration,
# so few options are available from system invocation.
"""

import os
import sys
import signal
import functools
import itertools
import typing
import json

from ..system import execution as libexec
from ..system.files import Path
from ..web import http
from ..internet import ri

from ..kernel import core as kcore
from ..kernel import dispatch as kdispatch
from ..kernel import io as kio
from ..kernel import flows as kflows

from ..time import types as timetypes
from ..time import sysclock

from . import service

class Service(kcore.Context):
	"""
	# Service daemon state and control interface.

	# Manages the interactions to daemons and commands.

	# Service processors do not exit unless the service is *completely* removed
	# by an administrative instruction; disabling a service does not remove it.
	# They primarily respond to events in order to keep the daemon running.
	# Secondarily, it provides the administrative interface.

	# [ Properties ]
	# /s_minimum_runtime/
		# Identifies the minimum time required to identify a successful start.
	# /s_retry_wait/
		# Duration to wait before automatically attemping to start the daemon again.
	# /s_maximum_attempts/
		# Limit of attempts to make before giving up and inhibiting daemon start.
	"""

	s_minimum_runtime = timetypes.Measure.of(second=16)
	s_retry_wait = timetypes.Measure.of(second=2)
	s_maximum_attempts = 8

	def structure(self):
		p = [
			('s_status', self.s_status),
			('s_actuates', self.s_config.actuates),
			('s_identifier', self.s_config.identifier),
			('s_invocation', self.s_invocation),
		]

		return (p, [])

	s_critical = "critical.log"

	s_status = 'unknown'
	s_config = None
	s_invocation = None
	s_inhibit_recovery = None
	s_exit_events = ()

	def __init__(self, service_config:service.Configuration):
		self.s_config = service_config
		self.s_exit_events = []
		self.s_status = 'terminated'
		self.s_process = None

	def actuate(self):
		self.controller.scheduling()
		self.s_update()
		self.s_last_known_time = sysclock.now()

		if self.s_config.actuates:
			self.critical(self.s_invoke)

	def s_invoke(self):
		"""
		# Invoke the service. Does nothing if &s_status is `'executed'`.
		"""

		if self.s_status == 'executed' or not self.functioning:
			return False

		oldcwd = os.getcwd()
		try:
			self.s_status = 'executed'
			service = self.s_config

			os.chdir(service.route.fullpath)
			fd = os.open(self.s_critical, os.O_APPEND|os.O_WRONLY|os.O_CREAT)

			subproc = kdispatch.Subprocess.from_invocation(self.s_invocation, stderr=fd, stdout=1)
			self.xact_dispatch(kcore.Transaction.create(subproc))
			self.s_last_known_time = sysclock.now()
			os.close(fd)
			self.s_process = subproc
		except BaseException as exc:
			self.s_status = 'exception'
			raise
		finally:
			os.chdir(oldcwd)

		return True

	def s_was_running(self):
		lkt = self.s_last_known_time
		try:
			duration = lkt.measure(self.s_exit_events[-1][0])
		except:
			return False

		if duration >= self.s_minimum_runtime:
			return True
		else:
			return False

	def s_again(self):
		"""
		# Called when a service process exits.
		"""

		if self.s_was_running():
			del self.s_exit_events[:]
			self.s_invoke()
		elif len(self.s_exit_events) >= self.s_maximum_attempts:
			# Force administrative intervention.
			self.s_inhibit_recovery = True
			self.s_status = 'exits'
		else:
			self.s_status = 'waiting'
			self.controller.scheduler.defer(self.s_retry_wait, self.s_invoke)

	def s_update(self):
		"""
		# Create or Update the KInvocation instance used to launch the daemon.
		"""

		# KInvocation used to run the command.
		service = self.s_config
		command_def = service.execution()
		if command_def[0] is None:
			command_def = ()
			return

		env = dict(os.environ.items())

		if service.environment:
			env.update(service.environment)

		env['SERVICE_NAME'] = service.identifier

		ki = libexec.KInvocation(*command_def, environ=env, set_process_group=True)
		self.s_invocation = ki

	def xact_void(self, xact):
		if self.terminating:
			self.finish_termination()
			return

		subproc = xact.xact_context
		if subproc is self.s_process:
			self.s_process = None

		pid_exit = subproc.sp_only

		if self.s_status != 'exception':
			self.s_status = 'terminated'

		self.s_exit_events.append((sysclock.now(), pid_exit))
		self.s_last_exit_status = pid_exit

		if self.s_inhibit_recovery != True:
			if self.s_config.actuates:
				self.s_again()
			elif self.s_inhibit_recovery == False:
				# restarted
				self.s_inhibit_recovery = None
				self.s_again()

	def s_get_pid(self):
		pid = self.s_process
		if pid is not None:
			pid, = pid.sp_processes.keys()
		return pid

	def s_terminate(self):
		del self.s_exit_events[:]
		self.s_process.sp_signal(signal.SIGTERM)

	def s_interrupt(self):
		del self.s_exit_events[:]
		self.s_process.sp_signal(signal.SIGINT)

	def s_kill(self):
		del self.s_exit_events[:]
		self.s_process.sp_signal(signal.SIGKILL)

	def s_suspend(self):
		self.s_process.sp_signal_group(signal.SIGSTOP)

	def s_continue(self):
		self.s_process.sp_signal_group(signal.SIGCONT)

	def terminate(self):
		if not self.functioning:
			return

		self.start_termination()
		if self.s_process is not None and not self.s_process.terminated:
			self.s_terminate()
		else:
			self.finish_termination()

class Control(kcore.Context):
	@staticmethod
	def prepare_http_v1(ifx, ports, Protocol=http.allocate_server_protocol):
		return [(x, (), Protocol()) for x in ports]

	def __init__(self, path, rootset):
		ep = kio.endpoint('local', str(path.container), path.identifier)
		self.ctl_interface = ep
		self.ctl_set = rootset
		self.ctl_completion = {}

	def actuate(self):
		self.provide('control')

		cxns = kio.Connections(self.ctl_http_processor)
		self.xact_dispatch(kcore.Transaction.create(cxns))

		ifi = kio.Interface(cxns.cxn_accept, self.prepare_http_v1)
		self.xact_dispatch(kcore.Transaction.create(ifi))

		ifi.if_install(self.system.bindings(self.ctl_interface))

	def xact_exit(self, xact):
		cb = self.ctl_completion.pop(xact.xact_context, None)
		if cb is not None:
			self.enqueue(cb)

	def xact_void(self, final):
		self.finish_termination()

	def terminate(self):
		if not self.functioning:
			return

		self.start_termination()
		for xact in self.xact_subxacts:
			xact.terminate()

	def ctl_select(self, s_identifier):
		return self.rootset.r_services[s_identifier]

	def ctl_update(self, http, data):
		# Called after receiving all data from a client.
		delta = None
		created = False
		rs = self.ctl_set
		inv, connect_output, channel_id, r, headers, struct, service_id = http

		try:
			buf = []
			for x in data:
				buf.extend(x)
			data = b''.join(buf)
			del buf

			if data.strip():
				delta = json.loads(data)
		except:
			self._ctl_http_send(http, b'400', b'BAD REQUEST', "could not load json entity body")
			return

		try:
			if delta is None:
				delta = {}

			s = rs.r_services.get(service_id)

			if s is None:
				path = (rs.r_path/'daemons'/service_id)
				config = service.Configuration(path, service_id)
				if not config.route.exists():
					created = True
					config.prepare()

				s = Service(config)
				rs.r_dispatch(s)
			else:
				config = s.s_config

			config.update(delta)
			config.store()
		except Exception as err:
			self._ctl_http_send(http, b'500', b'INTERNAL SERVER ERROR', "exception raised during operation")
		else:
			if created:
				self._ctl_http_send(http, b'201', b'CREATED', "service created")
			else:
				self._ctl_http_send(http, b'200', b'OK', "service update")

	def _ctl_http_send(self, http, code, descr, objects, no_body=False):
		(inv, connect, channel_id, r, headers, struct, service_id) = http

		output = json.dumps(objects).encode('utf-8')
		if no_body:
			output_source = None
		else:
			itc = kflows.Iteration([(output,)])
			output_source = kflows.Relay(inv.i_catenate, channel_id)

			xf = kio.Transfer()
			ox = kcore.Transaction.create(xf)
			self.xact_dispatch(ox)
			xf.io_flow([itc, output_source])

		outlen = len(output or b'')
		if outlen:
			headers.append((b'Content-Length', str(outlen).encode('utf-8')))
		headers.append((b'Content-Type', b'application/json'))

		connect((code, descr, headers, outlen), output_source)

	def ctl_http_processor(self, invp):
		# This is not efficient nor is it desired to be concerned with efficiency.
		# Service manipulations are expected to be rare and often directly by administration.

		close = False
		rs = self.ctl_set
		rl, events = invp.inv_accept()
		common_headers = [(b'Server', b'limiated-api-acces')]

		# Iterate over requests.
		for connect_output, inputctl in zip(rl, events):
			output = None
			code = None
			descr = None
			headers = list(common_headers)
			service = None
			command = 'select'

			channel_id, parameters, connect_input = inputctl
			method, uri, headers = parameters

			struct = http.Structures(headers)
			if (struct.connection or b'close') == b'close':
				headers.append((b'Connection', b'close'))
				close = True

			if method == b'OPTIONS' and uri == b'*':
				headers.append((b'Allow', b'GET,HEAD,POST,DELETE'))
				connect_input(None)
				connect_output((b'204', b'NO CONTENT', headers), None)
				continue

			r = ri.parse(uri.decode('utf-8'))
			r['host'] = struct.host
			path = r.get('path')

			# Check path and find command.
			if not path:
				service_id = None
				http_params = (invp, connect_output, channel_id, r, headers, struct, None)
				command = 'index'
			else:
				service_id = path[0]
				http_params = (invp, connect_output, channel_id, r, headers, struct, service_id)

				if len(path) > 1:
					connect_input(None)
					self._ctl_http_send(http_params, b'404', b'NOT FOUND', "services do not have subdirectories")
					continue

				if service_id == '*':
					pass
				elif method == b'POST' and (service_id not in rs.r_services or struct.content):
					# Service creation.
					reader = kio.Transfer()
					rx = kcore.Transaction.create(reader)
					storage = kflows.Collection.list()
					recv = kflows.Receiver(connect_input)

					callback = functools.partial(self.ctl_update, http_params, storage.c_storage)
					self.ctl_completion[reader] = callback
					self.xact_dispatch(rx)
					reader.io_flow([recv, storage])
					recv.f_transfer(None) # connect_input
					continue
				elif service_id not in rs.r_services:
					connect_input(None)
					self._ctl_http_send(http_params, b'404', b'NOT FOUND', "no such service")
					continue

			# Execute command.
			if 'query' in r:
				params = r.get('query', ())
				if params and params[0][1] is None:
					command = params[0][0]
					params = dict(params[1:])
				else:
					params = dict(params)
			else:
				params = None

			if service_id == '*' or service_id is None:
				service_identifiers = list(rs.r_services.keys())
				if params is not None:
					# Filter conditions.
					pass
			else:
				service_identifiers = [service_id]

			services = [rs.r_services[si] for si in service_identifiers]

			if method == b'POST':
				if command not in self.ctl_commands:
					code = b'400'
					descr = b'UNKNOWN SERVICE OPERATION'
					output = "command is not recognized"
				else:
					method = getattr(self, 'ctl_'+command)
					output = {}

					for si, service in zip(service_identifiers, services):
						output[si] = method(service_id, service, service.s_config)

					code = b'200'
					descr = b'OK'
			elif method in {b'GET', b'HEAD'}:
				if command == 'index':
					code = b'200'
					descr = b'OK'
					output = {x: y.s_status for x, y in rs.r_services.items()}
				elif command == 'select':
					code = b'200'
					descr = b'OK'

					output = {}
					for si, service in zip(service_identifiers, services):
						d = output[si] = service.s_config.snapshot()
						d.update({
							'status': service.s_status,
							'pid': service.s_get_pid(),
						})
				else:
					code = b'400'
					descr = b'BAD REQUEST'
			elif method == b'HEAD':
				pass
			elif method == b'DELETE':
				for s in services:
					if s.s_status == 'executed':
						code = b'409'
						descr = b'CONFLICT'
						output = "running services may not be removed"
						break
				else:
					for si, s in zip(service_identifiers, services):
						s.s_inhibit_recovery = True
						s.terminate()
						s.s_config.void()
					code = b'200'
					descr = b'OK'
					output = "service daemon directories have been removed"
			else:
				code = b'405'
				descr = b'METHOD NOT ALLOWED'
				output = "unsupported http method provided by client"

			connect_input(None)
			self._ctl_http_send(http_params, code, descr, output, no_body=(method==b'HEAD'))

		if close:
			invp.i_close()

	ctl_commands = set([
		'status',

		'reload',
		'normalize',
		'disable',
		'enable',

		'restart',
		'stop',
		'start',
		'interrupt',
		'kill',

		'sleep',
		'hold',
		'release',
	])

	def ctl_status(self, serivce_id, context, config):
		"""
		# Return the status of the service process.
		"""
		return context.s_status

	def ctl_suspend(self, service_id, context, config):
		"""
		# Send a stop signal to the service.
		"""

		if context.s_status == 'executed':
			context.s_suspend()
			return "service signalled to pause"
		else:
			return "cannot signal service when not running"

	def ctl_continue(self, service_id, context, config):
		"""
		# Send a continue signal to the service.
		"""

		if context.s_status == 'executed':
			context.s_continue()
			return "service signalled to continue"
		else:
			return "cannot signal service when not running"

	def ctl_enable(self, service_id, context, config):
		"""
		# Enable the service, but do not start it.
		"""

		config.actuates = True
		config.store_actuation()

		return "enabled"

	def ctl_disable(self, service_id, context, config):
		"""
		# Disable the service, but do not change its status.
		"""

		config.actuates = False
		config.store_actuation()

		return "disabled"

	def ctl_stop(self, service_id, context, config):
		"""
		# Signal the service to stop and inhibit it from being restarted if enabled.
		"""

		if config.actuates:
			context.s_inhibit_recovery = True
		else:
			# No need.
			context.s_inhibit_recovery = None

		if context.s_status != 'executed':
			return "stop ineffective when not running"

		context.s_terminate()
		return "daemon signalled to terminate"

	def ctl_restart(self, service_id, context, config):
		"""
		# Signal the service to stop (SIGTERM) and allow it to restart.
		"""

		if context.s_status != 'executed':
			return "restart ineffective when not running"

		context.s_inhibit_recovery = False
		context.s_terminate()

		return "daemon signalled to restart"

	def ctl_reload(self, service_id, context, config):
		"""
		# Send a SIGHUP to the service or launch the update command.
		"""

		if context.s_status == 'executed':
			context.s_reload()
			return "daemon signalled to reload using SIGHUP"
		else:
			return "reload ineffective when service is not running"

	def ctl_start(self, service_id, context, config):
		"""
		# Start the daemon unless it's already running; explicit starts ignore
		# &service.Configuration.actuates.
		"""

		if context.s_status == 'executed':
			return "already running"
		else:
			context.s_invoke()
			return "invoked"

	def ctl_normalize(self, service_id, context, config):
		"""
		# Normalize the state of the service.
		"""
		enabled = config.actuates
		status = context.s_status

		if enabled and status != 'executed':
			context.s_inhibit_recovery = False
			context.s_invoke()
			return "invoked"
		elif not enabled and status == 'executed':
			return self.ctl_stop(service_id, context, config)
		else:
			return "ineffective"

	def ctl_interrupt(self, service_id, context, config):
		"""
		# Interrupt the service.
		"""

		if config.actuates:
			context.s_inhibit_recovery = True
		else:
			# No need.
			context.s_inhibit_recovery = None

		if context.s_status != 'executed':
			return "interrupt ineffective when not running"

		context.s_interrupt()
		return "daemon signalled to interrupt"

	def ctl_kill(self, service_id, context, config):
		"""
		# Force the daemon process to exit.
		"""

		if config.actuates:
			context.s_inhibit_recovery = True
		else:
			# No need.
			context.s_inhibit_recovery = None

		if context.s_status != 'executed':
			return "kill ineffective when not running"

		context.s_kill()
		return "kill issued to service process"

	def ctl_void(self, service_id, context, config):
		"""
		# Terminate the service and destroy its daemon directory.
		"""

		del context.controller.controller.r_services[service_id]
		context.s_inhibit_recovery = True
		context.s_void()
		return "daemon directory will be destroyed after process termination"

class Set(kcore.Context):
	"""
	# Set of &Service transactions managing the presence of the service process.
	"""

	def __init__(self, route):
		self.r_path = route
		self.r_daemons = None
		self.r_services = {} # name to xact context

	def structure(self):
		p = [
			('r_path', self.r_path),
		]
		return (p, [])

	def xact_void(self, final):
		if self.terminating:
			self.finish_termination()

	def xact_exit(self, xact):
		si = xact.xact_context.s_config.identifier
		del self.r_services[si]

	def actuate(self):
		"""
		# Create the faultd context if it does not exist.
		# This is performed in actuate because it is desirable
		# to trigger a &system.process.Panic when an exception occurs.
		"""

		self.system.process.system_event_connect(('signal', 'terminate'), self, self.r_terminate)

		srv = service.Configuration(self.r_path, 'rootd')
		if service.environment not in os.environ:
			os.environ[service.environment] = self.r_path.fullpath

		# check process running
		srv.prepare()
		srv.load()

		srv.pid = os.getpid()
		srv.store_pid()
		self.root = srv
		srv.critical("[<> started root daemon]")
		os.chdir(srv.route.fullpath)

		# root's service instance will be loaded again in boot.
		# this reference will be simply dropped.

		rd = self.r_daemons = self.r_path / 'daemons'
		srv_list = rd.subnodes()[0]
		self.r_services.update(
			(x.identifier, Service(service.Configuration(x, x.identifier)))
			for x in srv_list
		)

		self.critical(self.r_boot)

	def terminate(self):
		self.start_termination()
		for x in self.controller.iterprocessors():
			if x is not self:
				x.terminate()

	def r_terminate(self):
		from ..system import kernel
		import signal
		kernel.exit_by_signal(signal.SIGTERM)
		self.controller.controller.terminate()

	def r_dispatch(self, service:Service):
		"""
		# Dispatch a new service.
		"""
		self.r_services[service.s_config.identifier] = service
		xs = kcore.Transaction.create(service)
		self.xact_dispatch(xs)
		return xs

	def r_boot(self):
		"""
		# Dispatch all loaded service transactions.
		"""

		# Invocation; poll configuration and launch.
		for service_id, s in self.r_services.items():
			s.s_config.load()
			x = kcore.Transaction.create(s)
			self.xact_dispatch(x)
