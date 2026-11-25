% Higher Order Singular Value Decomposition
% Usage: [U,S] = hosvd(P,tol)
% -------------------------------------------------------------------------
% Calculates the hosvd decomposition of a given tensor:
% P = S x1 U{1} x2 U{2} ... xN U{N}
% -------------------------------------------------------------------------
% Inputs:
% P -> the tensor to be decomposed
% tol -> a tolerance to ignore singular vectors whose singular value is
% less than tol*(the biggest singular value)
% -------------------------------------------------------------------------
% Outputs:
% U -> singular matrices U (together in a cell)
% S -> core tensor

function [U,S] = hosvd(P,tol)
    %Gets the tensor dimensions
    siz = size(P);
    %Gets the number of dimensions
    N = length(siz);
    %Initializes the core tensor as being the original tensor
    S = P;
    %preallocates U
    U = cell(N,1);
    %iterates over the dimensions
    for i = 1:N
        Spd = n_mode(P,i);
        [Ua,Sa] = svd(Spd);
        k = 1;
        while (k <= size(Ua,2))&&(Sa(k,k)/Sa(1,1) > tol)
                U{i}(:,k) = Ua(:,k);
                k = k+1;
        end
        S = n_mode_product(S,U{i}',i);
    end
end