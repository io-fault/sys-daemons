"""
# Process management daemon.
"""
from ...system.files import Path
from ...system import process

from .. import root

def main(inv:process.Invocation) -> process.Exit:
	from ...kernel import system, core
	import os

	application = root.Set(Path.from_absolute(os.environ['DAEMONS']))
	wctl = root.Control(Path.from_path('if/http'), application)

	xactseq = core.Sequenced([application, wctl])
	process = system.dispatch(inv, xactseq)
	system.control()

if __name__ == '__main__':
	process.control(main, process.Invocation.system(environ=['DAEMONS', 'SERVICE_NAME']))
