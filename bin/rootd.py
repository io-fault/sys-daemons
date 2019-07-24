"""
# Process management daemon.
"""
from ...system.files import Path
from ...system import process

from .. import root

def main(inv:process.Invocation) -> process.Exit:
	from ...kernel import system
	import os
	application = root.Set(Path.from_absolute(os.environ['DAEMONS']))

	system.dispatch(inv, application)
	system.control()

if __name__ == '__main__':
	process.control(main, process.Invocation.system(environ=['DAEMONS', 'SERVICE_NAME']))
