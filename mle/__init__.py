from scipy.optimize import minimize
from theano import function, scan
import theano.tensor as T
from numpy import inf
import numpy as np
from math import pi
from collections import OrderedDict as OD
import logging

from util import hessian_
from memoize import memoize

__all__ = ['var', 'par', 'Normal', 'Uniform', 'Mix2']

def alltrue(vals):
    ret = 1
    for c in vals:
        ret = ret * (1 * c)
    return ret

def bound(logp, *conditions):
    return T.switch(alltrue(conditions), logp, -inf)

def var(name, label=None):
    return Variable(name, label)

def par(name, label=None, lower=None, upper=None):
    return Parameter(name, label, lower, upper)

class Variable(object):
    def __init__(self, name, label=None):
        self.name = name
        if label:
            self.label = label
        else:
            self.label = name
        self.tvar = T.vector(name)

class Parameter(object):
    def __init__(self, name, label=None, lower=None, upper=None):
        self.name = name
        if label:
            self.label = label
        else:
            self.label = name
        self.lower = lower
        self.upper = upper
        self.tvar = T.scalar(name)

class Distribution(object):
    def __init__(self):
        self.var = OD()
        self.param = OD()
        self.dist = OD()

    def _add_var(self, var):
        self.var[var.name] = var
        return var.tvar

    def _add_param(self, param, enforce_lower=None, enforce_upper=None):
        self.param[param.name] = param
        return param.tvar

    def _add_dist(self, dist, name):
        self.dist[name] = dist
        return dist

    def get_vars(self):
        ret = []
        unique = []
        ret += self.var.values()
        for dist in self.dist.values():
            ret += dist.get_vars()
        for par in ret:
            if par not in unique:
                unique.append(par)
        return unique

    def get_params(self):
        ret = []
        unique = []
        ret += self.param.values()
        for dist in self.dist.values():
            ret += dist.get_params()
        for par in ret:
            if par not in unique:
                unique.append(par)
        return unique

    def get_dists(self):
        return self.dist.values()

    def _get_vars_pars(self):
        variables = list(self.get_vars())
        parameters = list(self.get_params())

        var_args = []
        for var in variables:
            var_args.append(var.tvar)

        par_args = []
        for par in parameters:
            par_args.append(par.tvar)

        return var_args, par_args

    @memoize
    def logp_compiled(self):
        logging.info('Compiling logp...')
        vars, pars = self._get_vars_pars()
        return function(vars + pars, -T.sum(self.logp()))

    @memoize
    def grad_compiled(self):
        logging.info('Compiling grad_logp...')
        vars, pars = self._get_vars_pars()
        return function(vars + pars, T.grad(-T.sum(self.logp()), pars))

    @memoize
    def hessian_compiled(self):
        logging.info('Compiling f_hessian...')
        vars, pars = self._get_vars_pars()
        return function(vars + pars, hessian_(-T.sum(self.logp()), pars)[0])

    def fit(self, data, init):
        variables = list(self.get_vars())
        parameters = list(self.get_params())

        data_args = []
        for var in variables:
            if var.name not in data:
                raise ValueError('Random variable {} required by model not found in dataset'.format(var.name))
            data_args.append(data[var.name])

        x0 = []
        for par in parameters:
            if par.name not in init:
                raise ValueError('No initial value specified for Parameter {}'.format(par.name))
            x0.append(init[par.name])

        obj_func = self.logp_compiled()
        obj_func_grad = self.grad_compiled()
        #obj_func_hessian = self.hessian_compiled()

        # We keep the data fixed while varying the parameters
        def func(pars):
            args = data_args + list(pars)
            return obj_func(*args)

        def func_grad(pars):
            args = data_args + list(pars)
            return  np.array(obj_func_grad(*args))

        #def func_hesse(pars):
        #    args = data_args + list(pars)
        #    ret = np.array(obj_func_hessian(*args))
        #    print(ret)
        #    return ret

        logging.info('Minimizing negative log-likelihood of model...')
        results =  minimize(func, jac=func_grad, x0=x0)

        ret = dict()

        for par, val in zip(parameters, results['x']):
            ret[par.name] = val

        #results.cov = np.linalg.inv(func_hesse(results.x))
        results.x = ret

        #err = dict()
        #for par, val in zip(parameters, np.sqrt(np.diag(results['cov']))):
        #    err[par.name] = val

        #results.err = err

        return results


class Uniform(Distribution):
    def __init__(self, x, lower=0, upper=1, *args, **kwargs):
        super(Uniform, self).__init__(*args, **kwargs)
        self.x = self._add_var(x)
        self.lower = self._add_param(lower)
        self.upper = self._add_param(upper)

    def logp(self):
        upper = self.upper
        lower = self.lower
        return T.log(1 / (upper - lower))

class Normal(Distribution):
    def __init__(self, x, mu=0, sigma=1, *args, **kwargs):
        super(Normal, self).__init__(*args, **kwargs)
        self.x = self._add_var(x)
        self.mu = self._add_param(mu)
        self.sigma = self._add_param(sigma, enforce_lower=0)

    def logp(self):
        x = self.x
        mu = self.mu
        sigma = self.sigma
        return bound(T.log(1/T.sqrt(2*pi*sigma**2) * T.exp(-0.5 * (x-mu)**2/sigma**2)), sigma > 0)

class Mix2(Distribution):
    def __init__(self, frac, dist1, dist2, *args, **kwargs):
        super(Mix2, self).__init__(*args, **kwargs)
        self.frac = self._add_param(frac)
        self.dist1 = self._add_dist(dist1, 'dist1')
        self.dist2 = self._add_dist(dist2, 'dist2')

    def logp(self):
        frac = self.frac
        dist1 = self.dist1
        dist2 = self.dist2
        return bound(T.log(frac * T.exp(dist1.logp()) + (1 - frac) * T.exp(dist2.logp())), frac > 0, frac < 1)

