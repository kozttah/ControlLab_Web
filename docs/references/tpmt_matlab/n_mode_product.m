% Calculates the n mode product of a tensor and a matrix
% P = A x_n U
% P = = n_mode_product(A,U,n)

function P = n_mode_product(A,U,n)
    Pm = n_mode(A,n);
    Pm = U*Pm;
    size_vector = size(A);
    size_vector(n) = size(U,1);
    P = n_mode2tensor(Pm,n,size_vector);
end