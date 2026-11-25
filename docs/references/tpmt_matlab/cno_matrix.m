% returns the minimizing cost matrix given a common matrix
% the matrix must be sn and nn (minimization conditions)
% - the cost function here is (-log(det(T*T')) which in itself imposes that
%   the columns of T are LI and tries to minimize the size of the simplex
%
% Usage: [Um, T] = cno_matrix(U)
%
% Notes:
%  - The input matrix U should already be sn-nn
%  - Requires YALMIP to pose the optimization problem

function [Um, T] = cno_matrix(U)

%Calculate the convex hull of the points (if dim > 2)
if (size(U,2) > 2)
    K = convhulln(U(:,1:end-1));
    k = K(:,1);
else
    %otherwise just pick the extremal points
    u = U(:,1:end-1);
    [~,i] = max(u);
    [~,j] = min(u);
    k = [i;j];
end
   
%Reduce the problem to use only the convex hull points
Ur = U(k,:);

%variable declarations
%gets the size of the transformation matrix
r = size(U,2);
%declare the transformation matrix - decision variable
T = sdpvar(r,r,'full'); assign(T,eye(r));
%declare the transformed matrix - so that we can declare the
%restrictions
Um = Ur*T;

%declare the problem restrictions
%sn condition
F = [sum(Um,2) == ones(size(Um,1),1)];

%nn condition
for i = 1:size(Um,1)
    for j = 1:size(Um,2)
        F = F + [Um(i,j) >= 0];
    end
end

%cost declaration
cost = -log(det(T*T'));
% - this cost function was chosen because: 
% sqrt(trace(inv(T')*inv(T))), is the norm of
% the matrix representing the triangle(before transforming). Minimizing 
% sqrt(trace(inv(T')*inv(T))) is equivalent to minimizing
% trace(inv(T')*inv(T)). Since the trace is equal to the sum of the
% eigenvalues, and the determinant is qual to their product, minimizing
% det(inv(T*T')) = det(T*T')^(-1) should be a good approximation for it.
% Since we'd like to impose T*T' > 0 (which imposes that the columns of T
% are LI), it is equivalent to minimizing log(det(T*T')^(-1)) =
% -log(det(T*T'))

%tries to solve the optimization problem
solvesdp(F,cost,sdpsettings('usex0',1,'verbose',0));

%returns the values found
T = double(T);
Um = U*T;
end