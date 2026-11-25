% returns the minimizing cost matrix given a common matrix
% the matrix must be sn and nn (minimization conditions)
% - the cost function here is (-log(det(T)) which in itself imposes that
%   the columns of T are LI and tries to minimize the size of the simplex
%
% Usage: [Um, T] = cno_matrix_no_yalmip(U)
%
% Notes:
%  - The input matrix U should already be sn-nn
%  - Does not require YALMIP to pose the optimization problem

function [Um, T] = cno_matrix_no_yalmip(U)

%variable declarations
%gets the size of the transformation matrix
r = size(U,2);

%declares the initial condition (identity is always feasible in this case)
T0 = reshape(eye(r),r^2,1);

%mounts the linear inequalities matrices
%in matrix format we would have
%Ur*T >= 0
%using kronecker product to rewrite it as a vector equation we can write
%kron(I,Ur)*reshape(T,r^2,1) >= reshape(zeros(size(Ur),prod(size(Ur)),1);
%check the wikipedia page on kronecker products (or Bernstein's book) for
%more information
%A*x <= b
A = -kron(eye(r),U);
b = reshape(zeros(size(U)),numel(U),1);

%mounts the linear equalities matrices
%in matrix format we would have
%Ur*T*ones(r,1) == ones(size(Ur,1),1);
%using kronecker product to rewrite it as a vector equation we can write
%kron(ones(1,r),Ur)*reshape(T,r^2,1) == ones(size(Ur,1),1);
%check the wikipedia page on kronecker products (or Bernstein's book) for
%more information
%Aeq*x == beq
Aeq = kron(ones(1,r),U);
beq = ones(size(U,1),1);

%declares the options structure and sets some parameters
options = optimset('fmincon');
%options = optimset(options,'Algorithm','interior-point','Hessian','bfgs','Display','off');
%tava dando pau pra problema muito grande com o interior point... tive q
%trocar pro active set...
options = optimset(options,'Algorithm','active-set','Display','off');
options.MaxFunEvals = 20000; %sets a really big number so this doesn't stops the optimization
Tvec = fmincon(@volume_simplex,T0,A,b,Aeq,beq,[],[],[],options);

%mounts the return matrices
T = reshape(Tvec,r,r);
Um = U*T;

end

%cost function
function cost = volume_simplex(Tvec)
    r = sqrt(numel(Tvec));
    T = reshape(Tvec,r,r);
    cost = -log(det(T));
end