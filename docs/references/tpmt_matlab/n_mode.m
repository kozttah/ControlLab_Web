% Finds the n mode matrix representation (Pm) of the tensor (Pt)
% Pm = n_mode(Pt,n)

function Pm = n_mode(Pt,n)
%Gets the tensor dimensions
siz = size(Pt);
%Gets the number of dimensions
N = length(siz);
%If the number of dimensions is less than the specified mode, add singleton
%dimension untill they are equal
if n> N
    siz = [siz ones(1,n-N)];
    N = n;
end
%Criate and index cell (so we can get the indexes by using ind2sub)
indice = cell(1,N);
%Preallocate Pm for efficiency
Pm = zeros(siz(n),numel(Pt)/siz(n));
%Transform to the n mode matrix
for ind = 1:numel(Pt)
    [indice{:}] = ind2sub(siz,ind);
    %get the row index
    row = indice{n};
    %get the collumn index
    if (n-1) > 0
        mul = siz(n-1);
        col = indice{n-1};
        for k = (n-2):(-1):1
            col = col + mul*(indice{k}-1);
            mul = mul*siz(k);
        end
        for k = N:(-1):(n+1)
            col = col + mul*(indice{k}-1);
            mul = mul*siz(k);
        end
    else
        mul = siz(N);
        col = indice{N};
        for k = (N-1):(-1):(n+1)
            col = col + mul*(indice{k}-1);
            mul = mul*siz(k);
        end
    end
    Pm(row,col) = Pt(ind);
end
end