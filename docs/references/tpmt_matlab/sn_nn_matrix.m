% returns a SN-NN matrix given a common matrix
% -------------------------------------------------------------------------
% USAGE
%
% [Unn, T] = sn_nn_matrix(U,tol)
%
% INPUTS
% U   -> input matrix to be transformed
% tol -> residue tolerance, that stabilishes wether or not an sn
%        transformation is feasible for the input matrix
%
% OUTPUTS
% Unn -> transformed matrix, having the sn and nn characteristics
% T   -> transformation matrix -> Unn = U*T
%--------------------------------------------------------------------------
%Note: Check the dimension of the Unn matrix, it may be bigger than the
%original (only increased in cases where its not possible to find a SN
%matrix with the input matrix)

function [Unn, T] = sn_nn_matrix(U,tol)
   %finds the least square solution for the sn transformation
   ls_sol = inv(U'*U)*U'*ones(size(U,1),1);
   %finds the least square residue
   res = (U*ls_sol - ones(size(U,1),1))'*(U*ls_sol - ones(size(U,1),1));
   
   %finds the sn transformation matrix and transforms the input matrix
   if res > tol
       Usn = [U (1-sum(U,2))];
       Tsn = eye(size(Usn,2));
   elseif size(U,2) == 1
       Tsn = ls_sol;
       Usn = U*ls_sol;
   else
       Tsn = eye(size(U,2));
       Tsn(1,2) = ls_sol(1) - 1;
       Tsn(size(U,2),size(U,2)-1) = ls_sol(size(U,2)) - 1;
       for i = 2:(size(U,2)-1)
           for j = (i-1):2:(i+1)
               Tsn(i,j) = (ls_sol(i) - 1)/2;
           end
       end
       Usn = U*Tsn;
   end
   
   %finds the nn transformation matrix and transforms the sn matrix
   %finds the smallest element of the matrix
    min_u = inf;
    for i=1:size(Usn,1)
        for j=1:size(Usn,2)
            if (Usn(i,j) < min_u)
                min_u = Usn(i,j);
            end
        end
    end
    
    %finds the zeta parameter
    if (min_u) >= -1
        zeta = 1;
    else
        zeta = 1/abs(min_u);
    end
    
    %finds the transformation matrix
    Tnn = (ones(size(Usn,2),size(Usn,2)) + zeta*eye(size(Usn,2)))/(size(Usn,2)+zeta);
    
    %Transforms the sn matrix into an sn-nn matrix
    Unn = Usn*Tnn;
    
    %Finds the SN-NN combined transformation matrix so that we can return
    %it
    T = Tsn*Tnn;
end