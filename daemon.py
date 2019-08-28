"""
# Sector Daemon management tools.
"""
import os
import sys
import functools
import itertools
import typing
import weakref

from ..system import execution
from ..system import process

from ..kernel import core as kcore
from ..kernel import dispatch as kdispatch
from ..kernel import system

class ProcessManager(kcore.Context):
	"""
	# Application context maintaining a pool of worker processes.
	"""

	def __init__(self, allocate, concurrency=4):
		self.ctl_concurrency = concurrency
		self.ctl_allocate = allocate
		self.ctl_fork_id_to_subprocess = weakref.WeakValueDictionary()
		self.ctl_last_exit_status = {}

	def actuate(self):
		for i in range(1, self.ctl_concurrency+1):
			self.ctl_fork(i)

	def xact_exit(self, xact):
		"""
		# Called when a fork's exit has been received by the controlling process.
		"""

		if self.terminating:
			return

		sub = xact.xact_context
		pid, fid = next(iter(sub.sp_processes.items())) # Only one.
		del self.ctl_fork_id_to_subprocess[fid]

		self.ctl_last_exit_status[fid] = (pid, sub.sp_only)

		# Restart Immediately.
		if fid < self.ctl_concurrency + 1:
			self.ctl_fork(fid)

	def xact_void(self, final):
		if self.terminating:
			self.finish_termination()

	def ctl_fork(self, fid):
		"""
		# Fork the process using the given &fid as its identifier.
		"""
		pid = process.Fork.dispatch(self.ctl_forked, fid)

		##
		# PARENT ONLY FROM HERE; child jumps into &ctl_forked
		##

		# Record forked process.
		subprocess = kdispatch.Subprocess(execution.reap, {pid: fid})

		self.ctl_fork_id_to_subprocess[fid] = subprocess
		self.xact_dispatch(kcore.Transaction.create(subprocess))

	def ctl_forked(self, fork_id):
		"""
		# Initial invocation of a newly forked process.
		# Indirectly invoked by &ctl_fork through &.system.Process.fork.
		"""

		os.environ["SECTORS"] = str(fork_id)
		system.__process_index__.clear()

		appctx, subinit = self.ctl_allocate()
		kprocess = system.dispatch(None, appctx, identifier='worker')
		system.set_root_process(kprocess)

		if subinit is not None:
			kprocess.enqueue(subinit)

		system.control()

	def terminate(self):
		if self.terminating:
			return

		self.start_termination()

		for x in self.controller.subtransactions:
			x.terminate()

		self.xact_exit_if_empty()
