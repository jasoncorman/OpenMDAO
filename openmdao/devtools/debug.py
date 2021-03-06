"""Various debugging functions."""

from __future__ import print_function

import sys
import os
from itertools import product, chain

import numpy as np
from contextlib import contextmanager
from six import iteritems, iterkeys, itervalues
from collections import Counter

from six.moves import zip_longest
from openmdao.core.problem import Problem
from openmdao.core.group import Group, System
from openmdao.core.implicitcomponent import ImplicitComponent
from openmdao.utils.mpi import MPI
from openmdao.approximation_schemes.finite_difference import FiniteDifference
from openmdao.approximation_schemes.complex_step import ComplexStep
from openmdao.utils.name_maps import abs_key2rel_key, rel_key2abs_key

# an object used to detect when a named value isn't found
_notfound = object()

def dump_dist_idxs(problem, vec_name='nonlinear', stream=sys.stdout):  # pragma: no cover
    """Print out the distributed idxs for each variable in input and output vecs.

    Output looks like this:

    C3.y     24
    C2.y     21
    sub.C3.y 18
    C1.y     17     18 C3.x
    P.x      14     15 C2.x
    C3.y     12     12 sub.C3.x
    C3.y     11     11 C1.x
    C2.y      8      8 C3.x
    sub.C2.y  5      5 C2.x
    C1.y      3      2 sub.C2.x
    P.x       0      0 C1.x

    Parameters
    ----------
    problem : <Problem>
        The problem object that contains the model.
    vec_name : str
        Name of vector to dump (when there are multiple vectors due to parallel derivs)
    stream : File-like
        Where dump output will go.
    """
    def _get_data(g, type_):

        sizes = g._var_sizes[vec_name][type_]
        vnames = g._var_allprocs_abs_names
        abs2meta = g._var_allprocs_abs2meta
        relevant = g._var_relevant_names[vec_name][type_]
        abs2idx = g._var_allprocs_abs2idx[vec_name]

        idx = 0
        data = []
        nwid = 0
        iwid = 0
        total = 0
        for rank in range(g.comm.size):
            for vname in vnames[type_]:
                if vname not in abs2idx:
                    continue
                ivar = abs2idx[vname]
                sz = sizes[rank, ivar]
                if sz > 0:
                    data.append((vname, str(total)))
                    nwid = max(nwid, len(vname))
                    iwid = max(iwid, len(data[-1][1]))
                    total += sz

        return data, nwid, iwid

    def _dump(g, stream):

        pdata, pnwid, piwid = _get_data(g, 'input')
        udata, unwid, uiwid = _get_data(g, 'output')

        data = []
        for u, p in zip_longest(udata, pdata, fillvalue=('', '')):
            data.append((u[0], u[1], p[1], p[0]))

        template = "{0:<{wid0}} {1:>{wid1}}     {2:>{wid2}} {3:<{wid3}}\n"
        for d in data[::-1]:
            stream.write(template.format(d[0], d[1], d[2], d[3],
                                         wid0=unwid, wid1=uiwid,
                                         wid2=piwid, wid3=pnwid))
        stream.write("\n\n")

    if not MPI or MPI.COMM_WORLD.rank == 0:
        _dump(problem.model, stream)


class _NoColor(object):
    """
    A class to replace Fore, Back, and Style when colorama isn't istalled.
    """
    def __getattr__(self, name):
        return ''


def _get_color_printer(stream=sys.stdout, colors=True, rank=0):
    """
    Return a print function tied to a particular stream, along with coloring info.
    """
    try:
        from colorama import init, Fore, Back, Style
        init(autoreset=True)
    except ImportError:
        Fore = Back = Style = _NoColor()

    if not colors:
        Fore = Back = Style = _NoColor()

    if MPI and MPI.COMM_WORLD.rank != rank:
        if rank >= MPI.COMM_WORLD.size:
            if MPI.COMM_WORLD.rank == 0:
                print("Specified rank (%d) is outside of the valid range (0-%d)." %
                      (rank, MPI.COMM_WORLD.size - 1))
            sys.exit()
        def color_print(s, **kwargs):
            pass
    else:
        def color_print(s, color='', end=''):
            """
            """
            print(color + s, file=stream, end='')
            print(Style.RESET_ALL, file=stream, end='')
            print(end=end)

    return color_print, Fore, Back, Style


def tree(top, show_solvers=True, show_jacs=True, show_colors=True, show_approx=True,
         filter=None, show_sizes=False, max_depth=0, rank=0, stream=sys.stdout):
    """
    Dump the model tree structure to the given stream.

    If you install colorama, the tree will be displayed in color if the stream is a terminal
    that supports color display.

    Parameters
    ----------
    top : System or Problem
        The top object in the tree.
    show_solvers : bool
        If True, include solver types in the tree.
    show_jacs : bool
        If True, include jacobian types in the tree.
    show_colors : bool
        If True and stream is a terminal that supports it, display in color.
    show_approx : bool
        If True, mark systems that are approximating their derivatives.
    filter : function(System)
        A function taking a System arg and returning None or an iter of (name, value) tuples.
        If None is returned, that system will not be displayed.  Otherwise, the system will
        be displayed along with any name, value pairs returned from the filter.
    show_sizes : bool
        If True, show input and output sizes for each System.
    max_depth : int
        Maximum depth for display.
    rank : int
        If MPI is active, the tree will only be displayed on this rank.  Only objects local
        to the given rank will be displayed.
    stream : File-like
        Where dump output will go.
    """
    cprint, Fore, Back, Style = _get_color_printer(stream, show_colors, rank=rank)

    tab = 0
    if isinstance(top, Problem):
        if filter is None:
            cprint('Driver: ', color=Fore.CYAN + Style.BRIGHT)
            cprint(type(top.driver).__name__, color=Fore.MAGENTA, end='\n')
            tab += 1
        top = top.model

    for s in top.system_iter(include_self=True, recurse=True):
        if filter is None:
            ret = ()
        else:
            ret = filter(s)
            if ret is None:
                continue

        depth = len(s.pathname.split('.')) if s.pathname else 0
        if max_depth != 0 and depth > max_depth:
            continue

        indent = '    ' * (depth + tab)
        cprint(indent, end='')

        info = ''
        if isinstance(s, Group):
            cprint("%s " % type(s).__name__, color=Fore.GREEN + Style.BRIGHT)
            cprint("%s" % s.name)
        else:
            if isinstance(s, ImplicitComponent):
                colr = Back.CYAN + Fore.BLACK + Style.BRIGHT
            else:
                colr = Fore.CYAN + Style.BRIGHT
            cprint("%s " % type(s).__name__, color=colr)
            cprint("%s" % s.name)
            if s.options['distributed']:
                cprint(" (distributed)", color=Fore.MAGENTA)

        # FIXME: these sizes could be wrong under MPI
        if show_sizes:
            cprint(" (%d / %d)" % (s._inputs._data.size, s._outputs._data.size),
                color=Fore.RED + Style.BRIGHT)

        if show_solvers:
            lnsolver = type(s.linear_solver).__name__
            nlsolver = type(s.nonlinear_solver).__name__

            if s.linear_solver is not None and lnsolver != "LinearRunOnce":
                cprint("  LN: ")
                cprint(lnsolver, color=Fore.MAGENTA + Style.BRIGHT)
            if s.nonlinear_solver is not None and nlsolver != "NonlinearRunOnce":
                cprint("  NL: ")
                cprint(nlsolver, color=Fore.MAGENTA + Style.BRIGHT)

        if show_jacs:
            jacs = []
            lnjac = nljac = None
            if s._assembled_jac is not None:
                lnjac = s._assembled_jac
                jacs.append(lnjac)
            if s.nonlinear_solver is not None:
                jacsolvers = list(s.nonlinear_solver._assembled_jac_solver_iter())
                if jacsolvers:
                    nljac = jacsolvers[0]._assembled_jac
                    if nljac is not lnjac:
                        jacs.append(nljac)

            if len(jacs) == 2:
                jnames = [' LN Jac: ', ' NL Jac: ']
            elif lnjac is not None:
                if lnjac is nljac:
                    jnames = [' Jac: ']
                else:
                    jnames = [' LN Jac: ']
            elif nljac is not None:
                jnames = [' NL Jac: ']
            else:
                jnames = []

            for jname, jac in zip(jnames, jacs):
                cprint(jname)
                cprint(type(jac).__name__, color=Fore.MAGENTA + Style.BRIGHT)

        if show_approx and s._approx_schemes:
            approx_keys = set()
            keys = set()
            for k, sjac in iteritems(s._subjacs_info):
                if 'method' in sjac and sjac['method']:
                    approx_keys.add(k)
                else:
                    keys.add(k)
            diff = approx_keys - keys
            cprint("  APPROX: ", color=Fore.MAGENTA + Style.BRIGHT)
            cprint("%s (%d of %d)" % (list(s._approx_schemes), len(diff), len(s._subjacs_info)))

        cprint('', end='\n')

        vindent = indent + '  '
        for name, val in ret:
            cprint("%s%s: %s\n" % (vindent, name, val))


def _get_printer(comm, stream):
    if comm.rank == 0:
        def p(*args, **kwargs):
            print(*args, file=stream, **kwargs)
    else:
        def p(*args, **kwargs):
            pass

    return p


def config_summary(problem, stream=sys.stdout):
    """
    Prints various high level statistics about the model structure.

    Parameters
    ----------
    problem : Problem
        The Problem to be summarized.
    stream : File-like
        Where the output will be written.
    """
    model = problem.model
    meta = model._var_allprocs_abs2meta
    locsystems = list(model.system_iter(recurse=True, include_self=True))
    locgroups = [s for s in locsystems if isinstance(s, Group)]

    grpnames = [s.pathname for s in locgroups]
    sysnames = [s.pathname for s in locsystems]
    ln_solvers = [(s.pathname, type(s.linear_solver).__name__) for s in locsystems
                              if s.linear_solver is not None]
    nl_solvers = [(s.pathname, type(s.nonlinear_solver).__name__) for s in locsystems
                         if s.nonlinear_solver is not None]

    max_depth = max([len(name.split('.')) for name in sysnames])
    setup_done = problem._setup_status == 2

    if problem.comm.size > 1:
        local_max = np.array([max_depth])
        global_max_depth = np.zeros(1, dtype=int)
        problem.comm.Allreduce(local_max, global_max_depth, op=MPI.MAX)

        proc_names = problem.comm.gather((sysnames, grpnames, ln_solvers, nl_solvers), root=0)
        grpnames = set()
        sysnames = set()
        ln_solvers = set()
        nl_solvers = set()
        if proc_names is not None:
            for systems, grps, lnsols, nlsols in proc_names:
                sysnames.update(systems)
                grpnames.update(grps)
                ln_solvers.update(lnsols)
                nl_solvers.update(nlsols)
    else:
        global_max_depth = max_depth
        ln_solvers = set(ln_solvers)
        nl_solvers = set(nl_solvers)

    ln_solvers = Counter([sname for _, sname in ln_solvers])
    nl_solvers = Counter([sname for _, sname in nl_solvers])

    # this gives us a printer that only prints on rank 0
    printer = _get_printer(problem.comm, stream)

    printer("============== Problem Summary ============")
    printer("Groups:           %5d" % len(grpnames))
    printer("Components:       %5d" % (len(sysnames) - len(grpnames)))
    printer("Max tree depth:   %5d" % global_max_depth)
    printer()

    if setup_done:
        desvars = model.get_design_vars()
        printer("Design variables:        %5d   Total size: %8d" %
                (len(desvars), sum(d['size'] for d in desvars.values())))

        con_nonlin_eq = {}
        con_nonlin_ineq = {}
        con_linear_eq = {}
        con_linear_ineq = {}
        for con, vals in iteritems(model.get_constraints()):
            if vals['linear']:
                if vals['equals'] is not None:
                    con_linear_eq[con] = vals
                else:
                    con_linear_ineq[con] = vals
            else:
                if vals['equals'] is not None:
                    con_nonlin_eq[con]= vals
                else:
                    con_nonlin_ineq[con]= vals

        con_nonlin = con_nonlin_eq.copy()
        con_nonlin.update(con_nonlin_ineq)
        con_linear = con_linear_eq.copy()
        con_linear.update(con_linear_ineq)

        printer("\nNonlinear Constraints:   %5d   Total size: %8d" %
                (len(con_nonlin), sum(d['size'] for d in con_nonlin.values())))
        printer("    equality:            %5d               %8d" %
                (len(con_nonlin_eq), sum(d['size'] for d in con_nonlin_eq.values())))
        printer("    inequality:          %5d               %8d" %
                (len(con_nonlin_ineq), sum(d['size'] for d in con_nonlin_ineq.values())))
        printer("\nLinear Constraints:      %5d   Total size: %8d" %
                (len(con_linear), sum(d['size'] for d in con_linear.values())))
        printer("    equality:            %5d               %8d" %
                (len(con_linear_eq), sum(d['size'] for d in con_linear_eq.values())))
        printer("    inequality:          %5d               %8d" %
                (len(con_linear_ineq), sum(d['size'] for d in con_linear_ineq.values())))

        objs = model.get_objectives()
        printer("\nObjectives:              %5d   Total size: %8d" %
                (len(objs), sum(d['size'] for d in objs.values())))

    printer()

    input_names = model._var_allprocs_abs_names['input']
    ninputs = len(input_names)
    if setup_done:
        printer("Input variables:         %5d   Total size: %8d" %
                (ninputs, sum(meta[n]['size'] for n in input_names)))
    else:
        printer("Input variables:         %5d" % ninputs)

    output_names = model._var_allprocs_abs_names['output']
    noutputs = len(output_names)
    if setup_done:
        printer("Output variables:        %5d   Total size: %8d" %
                (noutputs, sum(meta[n]['global_size'] for n in output_names)))
    else:
        printer("Output variables:        %5d" % noutputs)

    if setup_done and isinstance(model, Group):
        printer()
        conns = model._conn_global_abs_in2out
        printer("Total connections: %d   Total transfer data size: %d" %
                (len(conns), sum(meta[n]['size'] for n in conns)))

    printer()
    printer("Driver type: %s" % problem.driver.__class__.__name__)
    linstr = []
    for slvname, num in ln_solvers.most_common():
        if num > 1:
            linstr.append('{} x {}'.format(slvname, num))
        else:
            linstr.append(slvname)
    printer("Linear Solvers: [{}]".format(', '.join(linstr)))


    nlstr = []
    for slvname, num in nl_solvers.most_common():
        if num > 1:
            nlstr.append('{} x {}'.format(slvname, num))
        else:
            nlstr.append(slvname)
    printer("Nonlinear Solvers: [{}]".format(', '.join(nlstr)))


@contextmanager
def profiling(outname='prof.out'):
    """
    Context manager that runs cProfile on the wrapped code and dumps stats to the given filename.

    Parameters
    ----------
    outname : str
        Name of the output file containing profiling stats.
    """
    import cProfile
    prof = cProfile.Profile()
    prof.enable()

    yield prof

    prof.disable()
    prof.dump_stats(outname)


def compare_jacs(Jref, J, rel_trigger=1.0):
    results = []

    for key in set(J).union(Jref):
        if key in J:
            subJ = J[key]
        else:
            subJ = np.zeros(Jref[key].shape)

        if key in Jref:
            subJref = Jref[key]
        else:
            subJref = np.zeros(J[key].shape)

        diff = np.abs(subJ - subJref)
        absref = np.abs(subJref)
        rel_idxs = np.nonzero(absref > rel_trigger)
        diff[rel_idxs] /= absref[rel_idxs]

        max_diff_idx = np.argmax(diff)
        max_diff = diff.flatten()[max_diff_idx]

        # now determine if max diff is abs or rel
        diff[:] = 0.0
        diff[rel_idxs] = 1.0
        if diff.flatten()[max_diff_idx] > 0.0:
            results.append((key, max_diff, 'rel'))
        else:
            results.append((key, max_diff, 'abs'))

    return results


def trace_mpi(fname='mpi_trace', skip=(), flush=True):
    """
    Dump traces to the specified filename<.rank> showing openmdao and mpi/petsc calls.

    Parameters
    ----------
    fname : str
        Name of the trace file(s).  <.rank> will be appended to the name on each rank.
    skip : set-like
        Collection of function names to skip.
    flush : bool
        If True, flush print buffer after every print call.
    """
    if MPI is None:
        raise RuntimeError("MPI is not active.  Trace aborted.")
    if sys.getprofile() is not None:
        raise RuntimeError("another profile function is already active.")

    my_fname = fname + '.' + str(MPI.COMM_WORLD.rank)

    outfile = open(my_fname, 'w')

    stack = []

    _c_map = {
        'c_call': '(c) -->',
        'c_return': '(c) <--',
        'c_exception': '(c_exception)',
    }


    def _print_c_func(frame, arg, typestr):
        s = str(arg)
        if 'mpi4py' in s or 'petsc4py' in s:
            c = arg.__self__.__class__
            print('   ' * len(stack), typestr, "%s.%s.%s" %
                    (c.__module__, c.__name__, arg.__name__),
                    "%s:%d" % (frame.f_code.co_filename, frame.f_code.co_firstlineno),
                    file=outfile, flush=True)


    def _mpi_trace_callback(frame, event, arg):
        pname = None
        commsize = ''
        if event == 'call':
            if 'openmdao' in frame.f_code.co_filename:
                if frame.f_code.co_name in skip:
                    return
                if 'self' in frame.f_locals:
                    try:
                        pname = frame.f_locals['self'].msginfo
                    except:
                        pass
                    try:
                        commsize = frame.f_locals['self'].comm.size
                    except:
                        pass
                if pname is not None:
                    if not stack or pname != stack[-1][0]:
                        stack.append([pname, 1])
                        print('   ' * len(stack), commsize, pname, file=outfile, flush=flush)
                    else:
                        stack[-1][1] += 1
                print('   ' * len(stack), '-->', frame.f_code.co_name, "%s:%d" %
                      (frame.f_code.co_filename, frame.f_code.co_firstlineno),
                      file=outfile, flush=flush)
        elif event == 'return':
            if 'openmdao' in frame.f_code.co_filename:
                if frame.f_code.co_name in skip:
                    return
                if 'self' in frame.f_locals:
                    try:
                        pname = frame.f_locals['self'].msginfo
                    except:
                        pass
                    try:
                        commsize = frame.f_locals['self'].comm.size
                    except:
                        pass
                print('   ' * len(stack), '<--', frame.f_code.co_name, "%s:%d" %
                      (frame.f_code.co_filename, frame.f_code.co_firstlineno),
                      file=outfile, flush=flush)
                if pname is not None and stack and pname == stack[-1][0]:
                    stack[-1][1] -= 1
                    if stack[-1][1] < 1:
                        stack.pop()
                        if stack:
                            print('   ' * len(stack), commsize, stack[-1][0], file=outfile,
                                  flush=flush)
        else:
            _print_c_func(frame, arg, _c_map[event])

    sys.setprofile(_mpi_trace_callback)
