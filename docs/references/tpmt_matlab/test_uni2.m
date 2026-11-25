%% Limpa a área de trabalho, fecha os gráficos e limpa a janela de comandos
clear all; close all; clc;

%% modelo LPV
disp('modelo LPV');
syms theta;
B = [cos(theta) 0;
     sin(theta) 0;
     0          1]
 
disp('vetor de estados  -> [x y theta]');
disp('vetor de entradas -> [vt w]');

%% Tentativa de obter um modelo TS através do modelo LPV usando a
%  transformação TP (tensor-product) via HOSVD
disp('Obtendo modelo TP via HOSVD:');
disp('');
%% Passo 1 - Discretização esparsa do espaço e amostragem
disp('Passo 1 - Discretização esparsa do espaço e amostragem');

% Constroi grid esparso para a transformação
theta_t = -pi:(2*pi/100):pi;

%Prealoca Spd para aumentar velocidade
Bd = zeros(length(theta_t),size(B,1),size(B,2));

h_w = waitbar(0,'Amostrando discretização esparsa');
last = length(theta_t);
indice = 1;

% Discretiza Sp sobre os valores do grid
for cont_i = 1:length(theta_t)
    theta = theta_t(cont_i);
    Bd(cont_i,:,:) = subs(B);
    waitbar(indice/last,h_w)
    indice = indice + 1;
end

close(h_w);

%% Reconstrui numericamente a HOSVD-based canonical form
%% Passo 2 - Aproximação do tensor de núcleo via HOSVD
disp('Passo 2 - Aproximação do tensor de núcleo via HOSVD');
[U,Sd] = hosvd_sampled_func(Bd,2,1e-5);

figure(1);
plot(theta_t,U{1});
xlabel('\theta');
ylabel('$\mathbf{u}^{(1)}_i$');
legend('$\mathbf{u}^{(1)}_1$','$\mathbf{u}^{(1)}_2$','$\mathbf{u}^{(1)}_3$');

%% Transformação SN para as matrizes de peso
disp('Passo 4.2 - Transformação SN (sum normalized)');
%modo 1
[Usn1, Tsn1] = sn_matrix(U{1});
if size(Usn1,2) > size(U{1},2)
    Sd(size(Usn1,2),:,:,:,:,:) = 0*Sd((size(Usn1,2)-1),:,:,:,:,:);
end

% Transformação necessária em Sd
Sd = n_mode_product(Sd,inv(Tsn1),1);

%% Transformação NN para as matrizes de peso
disp('Passo 4.3 - Transformação NN (non negative)');
%modo 1
[Unn1, Tnn1] = nn_matrix(Usn1);

% Transformação necessária em Sd
Sd = n_mode_product(Sd,inv(Tnn1),1);

figure(2);
plot(theta_t,Unn1);
xlabel('\theta');
ylabel('$\mathbf{u}^{(1)}_i$');
legend('$\mathbf{u}^{(1)}_1$','$\mathbf{u}^{(1)}_2$','$\mathbf{u}^{(1)}_3$');


%% Transformação RNO-INO para as matrizes de peso
disp('Passo 4.4 - Transformação RNO-INO (relaxed normalized - inverted normalized)');

%modo 1
Urno1 = rno_ino_matrix(Unn1);
Trno1 = linsolve(Unn1,Urno1);

% Transformação necessária em Sd
Sd = n_mode_product(Sd,inv(Trno1),1);

figure(3);
plot(theta_t,Urno1);
xlabel('\theta');
ylabel('$\mathbf{u}^{(1)}_i$');
legend('$\mathbf{u}^{(1)}_1$','$\mathbf{u}^{(1)}_2$','$\mathbf{u}^{(1)}_3$');

%% Transformação CNO - jeito antigo
disp('Passo 4.5 - Transformação CNO (close to normalized) do jeito antigo');
%modo 1
[Ucno1, Tcno1, ~] = cno_opt_matrix(Urno1,deg2rad(60));

% Transformação necessária em Sd
Sd = n_mode_product(Sd,inv(Tcno1),1);

figure(4);
plot(theta_t,Ucno1);
xlabel('\theta');
ylabel('$\mathbf{u}^{(1)}_i$');
legend('$\mathbf{u}^{(1)}_1$','$\mathbf{u}^{(1)}_2$','$\mathbf{u}^{(1)}_3$');

%% Transformação CNO - jeito novo
disp('Passo 4.6 - Transformação CNO (close to normalized) do jeito novo');

[Ucno1n, T1n] = cno_matrix_no_yalmip(Ucno1);

% Transformação necessária em Sd
Sd = n_mode_product(Sd,inv(T1n),1);

figure(5);
plot(theta_t,Ucno1n);
xlabel('\theta');
ylabel('$\mathbf{u}^{(1)}_i$');
legend('$\mathbf{u}^{(1)}_1$','$\mathbf{u}^{(1)}_2$','$\mathbf{u}^{(1)}_3$');

%% Cálculo do erro de treinamento
aux1 = n_mode_product(Sd,Ucno1n,1);
aux2 = Bd - aux1;
mse = sum(sum(sum(aux2.^2)))