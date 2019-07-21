"""
# Sector daemon container.
"""

def main(inv:process.Invocation) -> process.Exit:
	return inv.exit(254)

	from ...kernel import system
	system.dispatch(inv, dl)
	system.control()

if __name__ == '__main__':
	process.control(main, process.Invocation.system(environ=['SERVICE_NAME']))
