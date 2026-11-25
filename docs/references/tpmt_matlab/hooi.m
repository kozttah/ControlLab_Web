% Higher Order Orthogonal Iteration
% Usage: [U,S] = hooi(P,ranks,Uinit,tol)
% -------------------------------------------------------------------------
% Calculates the hooi decomposition of a given tensor:
% P = S x1 U{1} x2 U{2} ... xN U{N}
% where each Matrix U{n} has an specified number of columns
% -------------------------------------------------------------------------
% Inputs:
% P -> the tensor to be decomposed
% ranks -> the desired number of columns for each matrix U
% Uinit -> an initial guess for U
% tol -> the tolerance that determines the convergence of the algorithm
% -------------------------------------------------------------------------
% Outputs:
% U -> matrices U (together in a cell)
% S -> core tensor

function [U,S] = hooi(P,ranks,Uinit,tol)
    %Gets the tensor dimensions
    siz = size(P);
    %Gets the number of dimensions
    N = length(siz);
    %stores the matrix unfoldings from tensor P
    Pn = cell(N,1);
    for i = 1:N
        Pn{i} = n_mode(P,i);
    end
    U = Uinit; %incorporates initial estimate
    %iterates until convergence of the U matrices
    delta = inf;
    while delta > tol
        Uold = U; delta = 0;
        for i = 1:N
            aux_mat = 1;
            for j = (i+1):N
                aux_mat = kron(aux_mat,U{j});
            end
            for j = 1:(i-1)
                aux_mat = kron(aux_mat,U{j});
            end
            aux_mat = Pn{i}*aux_mat;
            [ubar,sbar] = svd(aux_mat);
            U{i} = ubar(:,1:ranks(i));
            delta = delta + norm(U{i} - Uold{i});
        end
    end 
    %finds the S matrix
    S = P;
    for i = 1:N
        S = n_mode_product(S,U{i}',i);
    end
end