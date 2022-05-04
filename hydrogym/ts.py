import firedrake as fd
from firedrake import dx, ds
from ufl import inner, dot, nabla_grad, div

# Typing
from .flow import Flow
from typing import Optional, Iterable, Callable

class TransientSolver:
    pass

class IPCSSolver(TransientSolver):
    def __init__(self, flow: Flow, dt: float,
            callbacks: Optional[Iterable[Callable]] = [],
            time_varying_bc: bool = False):
        """
        callback(iter, t, flow)
        controller(t, y)
        """
        self.dt = dt
        self.t = 0
        self.callbacks = callbacks
        self.time_varying_bc = time_varying_bc

        self.flow = flow
        self.initialize_operators()

    def initialize_operators(self):
        # Setup forms
        flow = self.flow
        k = fd.Constant(self.dt)
        nu = fd.Constant(1/flow.Re)

        flow.init_bcs()
        V, Q = flow.function_spaces(mixed=False)

        # Boundary conditions
        self.bcu = flow.collect_bcu()
        self.bcp = flow.collect_bcp()

        # Trial/test functions for linear problems
        u = fd.TrialFunction(V)
        p = fd.TrialFunction(Q)
        v = fd.TestFunction(V)
        s = fd.TestFunction(Q)

        # Actual solution (references the underlying Flow object)
        self.u, self.p = flow.u, flow.p

        # Previous solution for multistep scheme
        self.u_n = self.u.copy(deepcopy=True)
        self.p_n = self.p.copy(deepcopy=True)

        # Combinations of functions for form construction
        U = 0.5*(self.u_n + u)  # Average for semi-implicit
        u_t = (u - self.u_n)/k  # Time derivative

        # Velocity predictor
        F1 = dot(u_t, v)*dx \
            + dot(dot(self.u_n, nabla_grad(self.u_n)), v)*dx \
            + inner(flow.sigma(U, self.p_n), flow.epsilon(v))*dx \
            + dot(self.p_n*flow.n, v)*ds - dot(nu*nabla_grad(U)*flow.n, v)*ds
            # - dot(f, v)*self.dx
        self.a1 = fd.lhs(F1)
        self.L1 = fd.rhs(F1)

        # Poisson equation
        a2 = dot(nabla_grad(p), nabla_grad(s))*dx
        self.L2 = dot(nabla_grad(self.p_n), nabla_grad(s))*dx - (1/k)*div(self.u)*s*dx

        # Projection step (pressure correction)
        a3 = dot(u, v)*dx
        self.L3 = dot(self.u, v)*dx - k*dot(nabla_grad(self.p - self.p_n), v)*dx

        # Assemble matrices
        self.A1 = fd.assemble(self.a1, bcs=self.bcu)
        self.A2 = fd.assemble(a2, bcs=self.bcp)
        self.A3 = fd.assemble(a3)

    def step(self, iter):
        self.t += self.dt  # Update current time
        
        # Step 1: Tentative velocity step
        if self.time_varying_bc:
            self.bcu = self.flow.collect_bcu()
            self.A1 = fd.assemble(self.a1, bcs=self.bcu)
        b1 = fd.assemble(self.L1, bcs=self.bcu)
        fd.solve(self.A1, self.u.vector(), b1, solver_parameters={
            "ksp_type": "gmres",
            "pc_type": "hypre",
            "pc_hypre_type": "boomeramg"
        })

        # Step 2: Pressure correction step
        b2 = fd.assemble(self.L2, bcs=self.bcp)
        fd.solve(self.A2, self.p.vector(), b2, solver_parameters={
            "ksp_type": "gmres",
            "pc_type": "hypre",
            "pc_hypre_type": "boomeramg"
        })

        # Step 3: Velocity correction step
        b3 = fd.assemble(self.L3)
        fd.solve(self.A3, self.u.vector(), b3, solver_parameters={
            "ksp_type": "cg",
            "pc_type": "sor"
        })

        # Update previous solution
        self.u_n.assign(self.u)
        self.p_n.assign(self.p)

        for cb in self.callbacks:
            cb(iter, self.t, (self.u, self.p))

    def solve(self, Tf):
        num_steps = int(Tf//self.dt)

        self.t = 0
        for iter in range(num_steps):
            self.step(iter)