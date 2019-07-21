"""
# Sector Daemon management library.

# In order to manage a daemon's execution, control interfaces must be supported to manage
# initialization and termination sequences. &.libdaemon provides access to these control
# interfaces so that the implementation can focus on regular operations.

# [ Features ]

	# - Set of forked processes or one if distribution is one.
	# - Arbitration for fork-local synchronization.

# /sys - Control Signalling Interface/
	# /interrupt/
		# Interrupt the application sectors causing near immediate shutdown.
	# /terminate/
		# Terminate the application sectors allowing exant work to complete.
	# /inject/
		# Introspection Interface; debugging; profiling

	# /circulate - Broadcasting Interface/
		# /coprocess/
			# Channel to other Processes in the daemon. (maybe virtual/implicit)
		# /site/
			# System Sets are closely connected (same system or network)
		# /application/
			# Set of sites; the entire graph

	# /message - Direct Messaging/
		# /fork-id/
			# .
		# /site/machine-id/fork-id/
			# .
		# /graph/site-id/machine-id/fork-id/
			# .
"""
import os
import sys
import functools
import collections
import itertools
import importlib
import typing

from ..system import python
from ..system import files

from ..kernel import core as kcore

from ..time import sysclock

def extract_sectors_config(document):
	pass

def serialize_sectors(struct, encoding="ascii", chain=itertools.chain.from_iterable):
	pass

class Control(core.Context):
	"""
	# Control Transaciton that manages the concurrency of a process and the control
	# interfaces thereof.

	# &Control handles both the controlling process and the workers
	# created with (system/manual)&fork calls.
	"""

	def __init__(self):
		self.ctl_fork_id = None # > 0 in slaves
		self.clt_fork_id_to_subprocess = {}
		self.ctl_subprocess_to_fork_id = {}

		# FUTURE connections to coprocesses
		self.connections = {}

	def actuate(self):
		assert self.ctl_fork_id is None # forks should not call actuate. ever.
		self.ctl_fork_id = 0 # root is zero

		# Manage termination of fork processes.
		#self.context.process.system_event_connect(('signal', 'terminate'), self, self.system_terminate)

		# stdout is closed; redirect print to stderr with a prefix
		import builtins
		dprint = builtins.print

		def errprint(*args, **kw):
			"""
			# Override for print to default to standard error and qualify origin in output.
			"""
			global sys
			nonlocal dprint, self

			kw.setdefault('file', sys.stderr)
			kw.setdefault('flush', True)
			sid = self.context.association().identity
			fid = self.ctl_fork_id
			pid = os.getpid()
			iso = sysclock.now().select('iso')

			dprint(
				"%s [x-sectord://%s:%d/python/builtins.print#%d]"%(
					iso.ljust(26, '0'), sid, fid, pid
				), *args, **kw
			)

		builtins.print = errprint

		self.route = files.Path.from_cwd()

		cid = (self.route / 'if')
		cid.init("directory")

		# address portion of the local socket
		cidstr = cid.fullpath

		unit = self.context.association()
		inv = unit.context.process.invocation
		ports = unit.ports

		args = inv.parameters['system']['arguments']
		for sector_exe in args:
			bsector, root, origin = rt_load_unit_sector(unit, sector_exe)

		# The control interface must be shut down in the forks.
		# The interchange is voided the moment we get into the fork,
		# despite the presence of Flows accepting sockets, the
		# traffic instance in the subprocess will know nothing about it.
		ports.bind(('control', 0), libkernel.endpoint('local', cidstr, "0"))
		self.ctl_install_control(0)

		config = self.route / 'sectors.cfg'
		# Bind the requested interfaces from invocation.xml
		structs = extract_sectors_config(config.load())
		for slot, (transport, binds) in structs['interfaces'].items():
			if transport != 'octets':
				continue
			ports.bind(slot, *list(itertools.starmap(libkernel.endpoint, binds)))

		# forking
		forks = self.concurrency = structs['concurrency']

		if forks:
			# acquire file system sockets before forking.
			# allows us to avoid some synchronizing logic after forking.
			for i in range(1, forks+1):
				ports.bind(('control', i), libkernel.endpoint('local', cidstr, str(i)))

			for i in range(1, forks+1):
				self.ctl_fork(i, initial=True)
		else:
			# normally rootd
			self.ctl_subactuate()

	def ctl_sectors_exit(self, unit):
		"""
		# Remove the control's interface socket before exiting the process.
		"""

		# Clean up file system socket on exit.
		fss = self.route / 'if' / str(self.ctl_fork_id)
		fss.void()

	def ctl_fork_exit(self, sub):
		"""
		# Called when a fork's exit has been received by the controlling process.
		"""

		fid = self.ctl_subprocess_to_fork_id.pop(sub)
		self.ctl_fork_id_to_subprocess[fid] = None

		pid, delta = sub.only
		typ, code, cored = delta

		# Restart Immediately. This will eventually get throttled.
		if fid < self.concurrency:
			self.ctl_fork(fid)

	def ctl_fork(self, fid, initial=False):
		"""
		# Fork the process using the given &fid as its identifier.
		"""
		assert self.ctl_fork_id == 0 # should only be called by master

		import signal as s

		filters = [functools.partial(s.signal, x, s.SIG_IGN) for x in (s.SIGTERM, s.SIGINT)]

		sed = self.context.process.system_event_disconnect
		#filters.append(functools.partial(sed, ('signal', 'terminal.query')))
		del sed, s

		pid = self.context.process.fork(filters, functools.partial(self.ctl_forked, fid, initial))
		del filters

		##
		# PARENT ONLY FROM HERE; child jumps into &ctl_forked
		##

		# Record forked process.
		subprocess = libkernel.Subprocess(pid)

		self.ctl_subprocess_to_fork_id[subprocess] = fid
		self.ctl_fork_id_to_subprocess[fid] = subprocess

		self.controller.dispatch(subprocess)
		subprocess.atexit(self.ctl_fork_exit)

	def ctl_forked(self, fork_id, initial=False):
		"""
		# Initial invocation of a newly forked process.
		# Indirectly invoked by &ctl_fork through &.system.Process.fork.
		"""

		self.ctl_fork_id = fork_id

		unit = self.context.association()

		os.environ["SECTORS"] = str(ctl_fork_id)

		# Setup control interface before subactuate
		self.ctl_install_control(ctl_fork_id)

		ports = unit.ports

		# close out the control interfaces of the parent and siblings
		s = set(range(self.concurrency+1))
		s.discard(ctl_fork_id)
		for x in s:
			ports.discard(('control', x))

		# The process needs to connect to the other forked processes
		# The initial indicator tells
		if initial:
			# connect using a specific pattern
			# 1: 2, 3, 4, ..., n
			# 2: 3, 4, ..., n
			# 3: 4, ..., n
			# 4: ..., n (opened by priors)
			# n: none (all others have connected to it)

			pass
		else:
			# connect to all coprocesses

			pass

		self.ctl_subactuate()

	def ctl_install_control(self, fid:int):
		"""
		# Setup the HTTP interface for controlling and monitoring the daemon.

		# [ Parameters ]
		# /fid
			# The fork-id; the number associated with the fork.
		"""

		sector = self.controller
		host = self.ctl_host = libweb.Host()
		host.h_update_mounts({'/sys/': Commands()})
		host.h_update_names('control')
		host.h_options = {}

		si = libkernel.Network(http.Server, host, host.h_route, (), ('control', fid))
		sector.process((host, si))

	def ctl_subactuate(self):
		"""
		# Called to actuate the sector daemons installed into (rt/path)`/bin`

		# Separated from &actuate for process forks.
		"""

		enqueue = self.context.enqueue
		enqueue(self.context._sys_traffic_flush)
		enqueue(self.ctl_actuate_binaries)

	def ctl_actuate_binaries(self):
		unit = self.context.association()
		exe_index = unit.u_hierarchy['bin']

		for exe in [unit.u_index[('bin', x)] for x in exe_index]:
			exe.actuate()
			exe._pexe_state = 1 # actuated
