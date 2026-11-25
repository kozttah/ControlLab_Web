% Modified Higher Order Singular Value Decomposition
% Usage: [U,S] = hosvd_sampled_func(P,ord_func,tol)
% -------------------------------------------------------------------------
% Calculates the hosvd decomposition of a given tensor:
% P = S x1 U{1} x2 U{2} ... x(N-ord_func) U{N-ord_func}
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
% tol -> a tolerance to ignore singular vectors whose singular value is
% less than tol*(the biggest singular value)
% -------------------------------------------------------------------------
% Outputs:
% U -> singular matrices U (together in a cell)
% S -> core tensor

function [U,S] = hosvd_sampled_func(P,ord_func,tol)
    %Gets the tensor dimensions
    siz = size(P);
    %Gets the number of dimensions
    N = length(siz);
    %Initializes the core tensor as being the original tensor
    S = P;
    %preallocates U
    U = cell(N-ord_func,1);
    %iterates over the dimensions
    for i = 1:(N - ord_func)
        Spd = n_mode(P,i);
        [Ua,Sa] = svd(Spd);
        k = 1;
        while (k <= min(size(Sa)))&&(Sa(k,k)/Sa(1,1) > tol)
                U{i}(:,k) = Ua(:,k);
                k = k+1;
        end
        S = n_mode_product(S,U{i}',i);
    end
end