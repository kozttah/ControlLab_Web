%Finds the rno-ino matrix for an n column input matrix
%Urno = rno_ino_matrix(U)

function Urno = rno_ino_matrix(U)
    r = size(U,2);
    U1{r} = U;
    for k = r:-1:3
        U1{k-1} = Ta(U1{k}(:,1:k-1),0);
    end
    U3{2} = rno_ino_2col(U1{2});
    for k = 3:r
        U2bar{k} = U3{k-1} - U1{k-1} + U1{k}(:,1:k-1);
        U3{k} = step(U2bar{k});
        U3{k}(:,k) = 1 - sum(U3{k},2);
    end 
    Urno = U3{r};
end

function Urno = step(U)
% we used to do the search with fmincon, but that seems overkill
%     a_otim = fmincon(@(a) cost(a,U),0,[],[],[],[],0,inf);
% so let's do a binary search
left = 0;
fl = cost_bin(left,U);
right = 1; fr = cost_bin(right,U);
    %make sure that we are surrounding the zero
    while fr < 0
        left = right; fl = fr;
        right = 2*right; fr = cost_bin(right,U);
    end
    mid = (right + left)/2; fm = cost_bin(mid,U);
    while (right-left > 1e-6) && (abs(fm) > 1e-6)
        if fm < 0
            left = mid;
        elseif fm > 0
            right = mid;
        else
            break;
        end
        mid = (right + left)/2; fm = cost_bin(mid,U);
    end
    a_otim = mid;
    
    Urno = Td(Tc(Tb(Ta(U,a_otim))));
end

function J = cost(a,U)
    Urno_a = Td(Tc(Tb(Ta(U,a))));
    aux = 1 - min(sum(Urno_a,2)) - max(Urno_a(:,1));
    J = aux^2;
end

function J = cost_bin(a,U)
    Urno_a = Td(Tc(Tb(Ta(U,a))));
    J = 1 - min(sum(Urno_a,2)) - max(Urno_a(:,1));
end


%Ta transformation
function Ua = Ta(U,a)
    Ua = 0*U;
    for i=1:size(U,1)
        aux = sum(U(i,:)) - 1;
        for j=1:size(U,2)
            Ua(i,j) = U(i,j) + (a-1)/(size(U,2))*aux;
        end
    end
end

%Tb transformation
function Ub = Tb(U)
    Ub = 0*U;
    for j = 1:size(U,2)
        min_uc = min(U(:,j));
        for i = 1:size(U,1)
            Ub(i,j) = U(i,j) - min_uc;
        end
    end
end

%Tc transformation
function Uc = Tc(U)
    Uc = 0*U;
    for j = 1:size(U,2)
        max_uc = max(U(:,j));
        for i = 1:size(U,1)
            Uc(i,j) = U(i,j)/max_uc;
        end
    end
end

%Td transformation
function Ud = Td(U)
    Ud = 0*U;
    max_sum = -inf;
    for i = 1:size(U,1)
        aux = sum(U(i,:));
        if aux > max_sum
            max_sum = aux;
        end
    end
    for i = 1:size(U,1)
        for j = 1:size(U,2)
            Ud(i,j) = U(i,j)/max_sum;
        end
    end
end

%Finds the rno-ino matrix for an 2 column input matrix
%Urno = rno_ino_2col(U)
function Urno = rno_ino_2col(U)
    p = U(:,1);
    min_p = min(p);
    max_p = max(p);
    Urno(:,1) = (p-min_p)./(max_p-min_p);
    Urno(:,2) = 1 - Urno(:,1);
end

