%Encontra modelo TS para uma função simples de duas variáveis
clear all; close all; clc;
%% Amostragem e representação tensorial - neste caso é uma matriz
%define grid em x1
x1 = linspace(-pi,pi,100);
%define grid em x2
x2 = linspace(-pi,pi,100);

%amostra função sobre domínio
func = zeros(100,100,2,2);
for i = 1:length(x1)
    for j = 1:length(x2)
        func(i,j,:,:) = [-1-sin(x2(j))*sin(x2(j)), 0.5*sin(x1(i))*sin(x1(i)); 0.5*cos(x1(i))*cos(x1(i)), -1-cos(x2(j))*cos(x2(j))];
    end
end


%% HOSVD
[C,Sd] = hosvd_sampled_func(func,2,1e-10);
%% Transformação SN

[Usn1, Tsn1] = sn_matrix(C{1});
if size(Usn1,2) > size(C{1},2)
    Sd(size(Usn1,2),:,:,:) = 0*Sd((size(Usn1,2)-1),:,:,:);
end

[Usn2, Tsn2] = sn_matrix(C{2});
if size(Usn2,2) > size(C{2},2)
    Sd(:,size(Usn2,2),:,:) = 0*Sd(:,(size(Usn2,2)-1),:,:);
end

Sd = n_mode_product(n_mode_product(Sd,inv(Tsn1),1),inv(Tsn2),2);

%% Transformação NN
%modo 1
[Unn1, Tnn1] = nn_matrix(Usn1);

%modo 2
[Unn2, Tnn2] = nn_matrix(Usn2);

Sd = n_mode_product(n_mode_product(Sd,inv(Tnn1),1),inv(Tnn2),2);

% %% Transformação CNO
% %modo 1
% [Ucno1,Trno1] = cno_matrix(Unn1);
% 
% %modo 2
% [Ucno2,Trno2] = cno_matrix(Unn2);
% 
% Sd = n_mode_product(n_mode_product(Sd,inv(Trno1),1),inv(Trno2),2);

%% Transformação RNO-INO
%modo 1
Ucno1 = rno_ino_matrix(Unn1);
Trno1 = linsolve(Unn1,Ucno1);

%modo 2
Ucno2 = rno_ino_matrix(Unn2);
Trno2 = linsolve(Unn2,Ucno2);

Sd = n_mode_product(n_mode_product(Sd,inv(Trno1),1),inv(Trno2),2);


%% Plota funções de pertinência
figure(1);
plot(x1,Ucno1);

figure(2);
plot(x2,Ucno2);

%% Cálcula erro de aproximação e plota superfície aproximada
U{1} = Ucno1;
U{2} = Ucno2;
mse = mse_app(func,U,Sd);

func_approx = n_mode_product(n_mode_product(Sd,Ucno1,1),Ucno2,2);
err = func - func_approx;
norm = frob_norm(err);
