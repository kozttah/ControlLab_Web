% Finds the tensor (Pt) from its n mode matrix representation (Pm)
% Pt = n_mode2tensor(Pm,n,size_vector)

function Pt = n_mode2tensor(Pm,n,size_vector)
%Gets the number of dimensions
N = length(size_vector);
%Criate and index cell (so we can get the indexes by using ind2sub)
indice = cell(1,N);
%Preallocate Pt for efficiency
Pt = zeros(size_vector);
%Transform n mode matrix to tensor representation
for ind = 1:numel(Pt)
    [indice{:}] = ind2sub(size_vector,ind);
    %get the row index
    row = indice{n};
    %get the collumn index
    if (n-1) > 0
        mul = size_vector(n-1);
        col = indice{n-1};
        for k = (n-2):(-1):1
            col = col + mul*(indice{k}-1);
            mul = mul*size_vector(k);
        end
        for k = N:(-1):(n+1)
            col = col + mul*(indice{k}-1);
            mul = mul*size_vector(k);
        end
    else
        mul = size_vector(N);
        col = indice{N};
        for k = (N-1):(-1):(n+1)
            col = col + mul*(indice{k}-1);
            mul = mul*size_vector(k);
        end
    end
    Pt(ind) = Pm(row,col);
end
end