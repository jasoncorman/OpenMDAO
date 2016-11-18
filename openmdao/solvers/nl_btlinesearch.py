"""Backtracking line search using the Armijo-Goldstein condition."""

from math import isnan

import numpy as np

from openmdao.solvers.solver import NonlinearSolver


class BacktrackingLineSearch(NonlinearSolver):
    """Backtracking line search using the Armijo-Goldstein condition."""

    SOLVER = 'NL: BK_TKG'

    def __init__(self, **kwargs):
        """Backtracking line search using the Armijo-Goldstein condition."""
        super(BacktrackingLineSearch, self).__init__(**kwargs)

        opt = self.options
        opt['maxiter'] = 5
        opt.declare('solve_subsystems', True,
                    desc='Set to True to solve subsystems. You may need '
                         'this for solvers nested under Newton.')
        opt.declare('rho', value=0.5, desc="Backtracking multiplier.")
        opt.declare('alpha', value=1.0, desc="Initial line search step.")
        opt.declare('rtol', value=0.9, desc="Relative error tolerance")
        # opt.declare('c', value=0.5, desc="Slope check trigger.")

    def _iter_initialize(self):
        """See openmdao.solvers.solver.Solver."""
        system = self._system
        self.alpha = self.options['alpha']

        u = system._outputs
        du = system._vectors['output']['']
        # lower = system.lower
        # upper = system.upper
        #
        # if not numpy.isnan(lower).all() \
        #    and not numpy.isnan(u).any() \
        #    and not numpy.isnan(du).any():
        #     lower_const = u + self.alpha * du - lower
        #     ind = numpy.nanargmin(lower_const)
        #     if lower_const[ind] < 0:
        #         self.alpha = (lower[ind] - u[ind]) / du[ind]
        # if not numpy.isnan(upper).all() \
        #    and not numpy.isnan(u).any() \
        #    and not numpy.isnan(du).any():
        #     upper_const = -(u + self.alpha * du - upper)
        #     ind = numpy.nanargmin(upper_const)
        #     if upper_const[ind] < 0:
        #         self.alpha = (upper[ind] - u[ind]) / du[ind]

        norm0 = self._iter_get_norm()
        if norm0 == 0.0:
            norm0 = 1.0
        u.add_scal_vec(self.alpha, du)
        norm = self._iter_get_norm()
        return norm0, norm

    def _iter_execute(self):
        """See openmdao.solvers.solver.Solver."""
        system = self._system
        u = system._outputs
        du = system._vectors['output']['']

        u.add_scal_vec(-self.alpha, du)
        self.alpha *= self.options['rho']
        u.add_scal_vec(self.alpha, du)
