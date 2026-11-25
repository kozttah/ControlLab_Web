% returns the minimizing cost matrix given a common matrix
% the matrix must be sn and nn (minimization conditions)
%
% Usage: [Um, T, diagnostics] = mgk_matrix(U)
%
% Note: may generate a bigger dimension matrix (in case the transformation
% is unfeasible)

function [Um, T, diagnostics] = mgk_matrix(U)
%checks the sn feasibility
%finds the least square solution for the sn transformation
ls_sol = inv(U'*U)*U'*ones(size(U,1),1);
%finds the least square residue
res = (U*ls_sol - ones(size(U,1),1))'*(U*ls_sol - ones(size(U,1),1));
%if its unfeasible, adds a new column
if res > eps
    U = [U (1-sum(U,2))];
end
%note-> its interesting to note that if the
%problem is unfeasible than the column of ones vector doesn't belong to the
%image space of U, therefore adding the column 1-sum(U,2) will always add
%an LI column to U

disp('variable declarations');
%gets the size of the transformation matrix
r = size(U,2);
%declare the transformation matrix - decision variable
T = sdpvar(r,r,'full'); assign(T,eye(r));
%declare the transformed matrix - so that we can declare the
%restrictions
Um = U*T;

disp('restrictions declarations');
%declare the problem restrictions

disp('sn condition');
F = [sum(Um,2) == ones(size(Um,1),1)];

disp('nn condition');
for i = 1:size(Um,1)
    for j = 1:size(Um,2)
        F = F + [Um(i,j) >= 0];
    end
end

disp('nonzero column condition');
%gets the number of positions
n = size(U,1);
%stabilishes a 10% representation limit for each column, unless we have
%more than 10 column. In that case adds an equal representation limit (for
%all columns)
if r < 10
    lim = 0.1;
else
    lim = 1/r;
end
%considering it can put all the values of a column with the same number,
%we want this value to be bigger than 0.01, so we want the column sum to
%be bigger than 0.01*n
for i = 1:size(Um,2)
    F = F + [sum(Um(:,i)) > lim*n];
end

%Declares the cost as being the interaction between non-adjoint
%membership functions
disp('cost function declaration');
cost = 0;
for i = 1:r
    for j = i+2:r
        cost = cost + (Um(:,i)'*Um(:,j))^2;
    end
end

%tries to solve the optimization problem
disp('calls the solver');
diagnostics = solvesdp(F,cost,sdpsettings('usex0',1,'verbose',1));

checkset(F)

%returns the values found
T = double(T);
Um = double(Um);
end