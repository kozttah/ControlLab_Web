% Modified Higher Order Orthogonal Iteration
% Usage: [U,S] = hooi_sampled_func(P,ord_func,ranks,Uinit,tol)
% -------------------------------------------------------------------------
% Calculates the hooi decomposition of a given tensor:
% P = S x1 U{1} x2 U{2} ... x(N-ord_func) U{N-ord_func}
% where each Matrix U{n} has an specified number of columns
% 
% This function was meant to be used when the hosvd is being used to find
% an approximate representantion of a sampled tensorial function
%
% The tensor should be in a way such that the last dimensions correspond to
% the dimensions of the functions image space
% -------------------------------------------------------------------------
% Inputs:
% P -> the tensor to be decomposed
% ord_func -> the order of the image space tensor of the function (0 for
%             scalar, 1 for vector, 2 for matrices, etc...)
% ranks -> the desired number of columns for each matrix U
% Uinit -> an initial guess for U
% tol -> the tolerance that determines the convergence of the algorithm
% -------------------------------------------------------------------------
% Outputs:
% U -> matrices U (together in a cell)
% S -> core tensor

function [U,S] = hooi_sampled_func(P,ord_func,ranks,Uinit,tol)
    %Gets the tensor dimensions
    siz = size(P);
    %Gets the number of dimensions
    N = length(siz);
    %stores the matrix unfoldings from tensor P
    Pn = cell(N-ord_func,1);
    for i = 1:(N - ord_func)
        Pn{i} = n_mode(P,i);
    end
    U = Uinit; %incorporates initial estimate
    %iterates until convergence of the U matrices
    delta = inf;
    while delta > tol
        Uold = U; delta = 0;
        for i = 1:(N - ord_func)
            aux_mat = 1;
            for j = (i+1):(N - ord_func)
                aux_mat = kron(aux_mat,U{j});
            end
            for j = (N - ord_func+1):N
                aux_mat = kron(aux_mat,eye(siz(j)));
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
    for i = 1:(N - ord_func)
        S = n_mode_product(S,U{i}',i);
    end
end