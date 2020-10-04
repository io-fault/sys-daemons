import sys
from .. import service as module

def test_service_routes(test):
	tr = test.exits.enter_context(module.Path.fs_tmpdir())
	for i in range(12):
		sr = tr / ('s'+str(i))
		sr.fs_mkdir()

	s = set(['s'+str(i) for i in range(12)])

	for bn, r in module.service_routes(tr):
		test/(bn in s) == True

def test_Configuration(test):
	tr = test.exits.enter_context(module.Path.fs_tmpdir())
	# create, store/load and check empty

	srv = module.Configuration(tr, "test-service")
	test/FileNotFoundError ^ srv.store

	srv.create()
	srv.store()
	srv.load()

	test/srv.actuates == False
	test/srv.parameters == []
	test/srv.environment == []

	# modify and store, then create new service to compare
	enabled = srv.actuates = True
	params = srv.parameters = ['--long-param', 'some', 'parameter']
	docs = srv.abstract = "SOME DOCUMENTATION"
	env = srv.environment = [("ENV1", "VALUE1"), ("ENV2", "VALUE2")]
	exe = srv.executable = "/sbin/somed"

	srv.store()

	srv2 = module.Configuration(tr, "test-service")
	srv2.load()
	test/srv2.executable == exe
	test/srv2.environment == env
	test/srv2.abstract == docs
	test/srv2.parameters == params
	test/srv2.actuates == enabled
	test/srv2.actuates == True

	# check the alteration.
	srv.actuates = False
	srv.store_actuation()
	srv2.load_actuation()
	test/srv2.actuates == False

if __name__ == '__main__':
	import sys
	from ...test import library as libtest
	libtest.execute(sys.modules[__name__])
