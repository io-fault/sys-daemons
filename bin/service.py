"""
# faultd service interface for automating configuration management during daemon downtime.

# Deals directly with the file system and should only be used while faultd is not running.
# Invoking without arguments displays help to standard error.
"""

import os
import sys

from ...context import string
from ...system.files import Path
from .. import core

def command_create(srv, *params):
	"Create the service directory and initialize its settings."

	if srv.exists():
		sys.stderr.write("service directory already exists\n")
		raise SystemExit(1)

	srv.create()
	srv.enabled = False

	if params:
		exe, *cparams = params
		srv.executable = exe
		srv.parameters = cparams

	try:
		srv.store()
	except:
		srv.void()
		raise

def command_void(srv):
	"Remove the service directory and its contents."

	if not srv.exists():
		sys.stderr.write("service directory does not exist\n")
		raise SystemExit(1)

	srv.route.void()

def command_define(srv, *params):
	"Define the executable and its parameters for starting the service."

	exe, *params = params

	srv.load()
	srv.executable = exe
	srv.parameters = params
	srv.libexec(recreate=True)

	srv.store()

def command_enable(srv):
	"Enable the service causing it to be started when faultd is ran."

	srv.load_actuation()
	srv.actuates = True
	srv.store_actuation()

def command_disable(srv):
	"Disable the service; attempts to start afterward will fail unless forced."

	srv.load_actuation()
	srv.actuates = False
	srv.store_actuation()

def command_environ_add(srv, *pairs):
	"Add the given settings as environment variables. (No equal sign used in assignments)"

	srv.load()
	srv.environment.extend(zip(pairs[::2], pairs[1::2]))
	srv.store_invocation()

def command_environ_del(srv, *varnames):
	"Remove the given environment variables from the service."

	srv.load()
	srv.environment = [
		x for x in srv.environment
		if x[0] not in varnames
	]

	srv.store_invocation()

def command_report(srv):
	"Report the service's definition to standard error."

	srv.load()
	name = srv.route

	command = [srv.executable]
	command.extend(srv.parameters)

	envvars = ' '.join(['%s=%r' %(k, v) for k, v in srv.environment])
	dir = srv.route.fullpath
	docs = (srv.route / 'readme.txt').load().decode('utf-8')

	report = """
		Service: {srv.identifier}
		Actuation: {srv.actuation}
		Directory: {dir}
		Command: {command}\n""".format(**locals())

	if docs:
		report += \
		"\t\tDocumentation: \n\n{docs}\n\n".format(docs=docs)
	else:
		report += '\n'

	sys.stderr.write(report)
	raise SystemExit(64) # EX_USAGE

def command_execute(srv):
	"For testing, execute the service (using exec) as if it were ran by faultd."

	srv.load()
	srv.execute()

def command_update(srv):
	"Recreate the hardlink for root and sectors."

	srv.load()
	srv.libexec(recreate=True)

command_synopsis = {
	'create': "executable name [parameters]",
	'env-add': "[VARNAME1 VALUE1 VARNAME2 VALUE2 ...]",
	'env-del': "[VARNAME1 VARNAME2 ...]",
}

command_map = {
	'void': command_void,
	'create': command_create,
	'command': command_define,
	'update': command_update,
	'enable': command_enable,
	'disable': command_disable,

	'env-add': command_environ_add,
	'env-del': command_environ_del,

	'execute': command_execute,
	'report': command_report,
}

def menu(route, syn=command_synopsis):
	commands = [
		(cname, cfunc.__doc__, cfunc.__code__.co_firstlineno)
		for cname, cfunc in command_map.items()
	]

	commands.sort(key=lambda x: x[2])

	head = "service [service_name] [command] ...\n\n"

	descr = "Modify the fault services' stored configuration. Modifications\n"
	descr += "apply directly to disk and do not effect "
	descr += "the running process unless reloaded.\n"
	descr += "\nThis should only be used prior starting faultd.\n"
	ctl = __package__ + '.control'
	descr += "Use {0} for interacting with a running faultd instance.\n".format(ctl)

	command_head = "\nCommands:\n\t"

	command_help = '\n\t'.join([
		cname + (' ' if cname in syn else '') + (syn.get(cname, "")) + '\n\t\t' + cdoc
		for cname, cdoc, lineno in commands
	])

	ddir = route / 'daemons'
	sl = ddir.subnodes()[0]
	service_head = "\n\nServices [%s][%d]:\n\n\t" %(route.fullpath, len(sl),)

	abstracts = [x.load() for x in (y/'abstract.txt' for y in sl)]
	services = [
		(x.identifier + ('\n\t' + string.indent(ab.decode('utf-8')) if ab else ''))
		for x, ab in zip(sl, abstracts)
	]
	service_list = '\n\t'.join(services) or '[None]'

	return ''.join([
		head, descr, command_head,
		command_help, service_head,
		service_list, '\n'
	])

def main(*args, fiod=None):
	if fiod is None:
		fiod = os.environ.get(core.environment)

		if fiod is None:
			# from builtin default
			fiod = core.default_route
			dsrc = 'default'
		else:
			# from env
			fiod = Path.from_absolute(fiod)
			dsrc = 'environment'
	else:
		fiod = Path.from_absolute(fiod)
		dsrc = 'parameter'

	if not args:
		# show help
		sys.stderr.write(menu(fiod))
		sys.stderr.write('\n')
		raise SystemExit(64) # EX_USAGE
	else:
		service, *args = args
		if args:
			command, *params = args
		else:
			command = 'report'
			params = args

		srvdir = fiod / 'daemons' / service
		si = core.Service(srvdir, service)
		ci = command_map[command]
		ci(si, *params)

if __name__ == '__main__':
	main(*sys.argv[1:])
