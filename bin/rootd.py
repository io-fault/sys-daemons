"""
# Service management daemon.

# Usually executed using &.boot.
"""
from fault.system.files import Path
from fault.system import process

from .. import root

def main(inv:process.Invocation) -> process.Exit:
	from ...kernel import system, core
	inv.imports(['DAEMONS', 'SERVICE_NAME'])

	application = root.Set(Path.from_absolute(inv.environ['DAEMONS']))
	wctl = root.Control(Path.from_path('if/http'), application)

	xactseq = core.Sequenced([application, wctl])
	process = system.dispatch(inv, xactseq)
	system.set_root_process(process)
	system.control()

if __name__ == '__main__':
	process.control(main, process.Invocation.system())
