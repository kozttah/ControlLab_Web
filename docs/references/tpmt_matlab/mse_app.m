% Calculates the mean squared error between the original tensor and the
% approximated one
% Usage: mse = mse_app(P,U,S)
function mse = mse_app(P,U,S)
    Pbar = S;
    for i = 1:length(U)
        Pbar = n_mode_product(Pbar,U{i},i);
    end
    error = P - Pbar;
    %Gets the tensor dimensions
    siz = size(error);
    %Gets the number of dimensions
    N = length(siz);
    summ = sum(error.^2);
    for i = 2:N
        summ = sum(summ);
    end
    mse = summ/numel(error);
end

