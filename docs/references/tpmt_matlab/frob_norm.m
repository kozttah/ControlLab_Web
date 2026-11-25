% Calculates the frobenius norm of a given tensor
% Usage: f = frob_norm(P)
function f = frob_norm(P)
    Pbar = P.^2;
    siz = size(Pbar);
    f = sum(Pbar);
    for i = 2:length(siz)
        f = sum(f);
    end
    f = sqrt(f);
end

