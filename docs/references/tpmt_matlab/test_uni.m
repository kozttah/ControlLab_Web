%% Esse é o jeito velho de fazer, entretanto é interessante pq é o único q 
%  faz uso do zerofill para fazer a interpolação (idéia apresentada na tese
%  do Zoltan Petres)
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
theta_t = -pi:(2*pi/10):pi;

%Prealoca Spd para aumentar velocidade
Spd = zeros(length(theta_t),size(B,1),size(B,2));

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
% Constroi as representações do modos 1
Bd1 = n_mode(Bd,1);

% Calculando o svd de cada um dos modos
% modo 1
[U,S] = svd(Bd1);
cont_j = 1;
for cont_i = 1:min([size(S,1) size(S,2)])
    if S(cont_i,cont_i) > 1e-4
        U1(:,cont_j) = U(:,cont_i);
        cont_j = cont_j+1;
    end
end

% Encontra o tensor núcleo S
clear U S V Bd1;
Sd = n_mode_product(Bd,U1',1);

%% Passo 3 - Aumentando a densidade do grid
disp('Passo 3 - Aumentando a densidade do grid');
% Constroi grid denso
% Constroi grid esparso para a transformação
theta_g = -pi:(2*pi/100):pi;

%Prealoca Spg para aumentar velocidade
Spg = zeros(length(theta_g),size(B,1),size(B,2));

disp('Passo 3.1 - Reamostragem densa');
h_w = waitbar(0,'Amostrando discretização densa');
last = length(theta_g);
indice = 1;

% Discretiza Sp sobre os valores do grid
for cont_i = 1:length(theta_g)
    theta = theta_g(cont_i);
    Spg(cont_i,:,:) = subs(B);
    waitbar(indice/last,h_w)
    indice = indice + 1;
end

close(h_w);

%%
% Preenche matrizes U com zeros para que a interpolação funcione
U1m = zerofill(U1,9);

%%
disp('Passo 3.2 - Interpolação das funções de peso');
% Fazendo a "interpolação" para encontrar Ug1
% Ug1

%aux1 = n_mode_product(n_mode_product(n_mode_product(Sd,U2m,2),U3m,3),U4m,4);
aux1 = Sd;
aux1 = n_mode(aux1,1);
aux1 = pinv(aux1);

Ug1 = n_mode(Spg,1)*aux1;

%% Passo 4 - Gerando o fecho convexo com a característica desejada
disp('Passo 4 - Gerando o fecho convexo com a característica desejada:')

% Como foi realizada uma interpolação para encontrar as matrizes Ug1 a Ug4
% estas não possuem mais a característica de ortogonalidade
% Então a primeira etapa a se realizar é esta ortogonalização e as devidas
% mudanças no tensor Sd (necessário para poder transformá-las em matrizes
% SN)

disp('Passo 4.1 - Ortogonalização');
% Ortogonalização
O1 = orth(Ug1); T1 = linsolve(Ug1,O1);

% Transformação necessária em Sd
Sd = n_mode_product(Sd,inv(T1),1);

%% Transformação SN para as matrizes de peso
disp('Passo 4.2 - Transformação SN (sum normalized)');
%modo 1
[Usn1, Tsn1] = sn_matrix(O1);
if size(Usn1,2) > size(O1,2)
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

%% Transformação RNO-INO para as matrizes de peso
disp('Passo 4.4 - Transformação RNO-INO (relaxed normalized - inverted normalized)');

%modo 1
Urno1 = rno_ino_matrix(Unn1);
Trno1 = linsolve(Unn1,Urno1);

% Transformação necessária em Sd
Sd = n_mode_product(Sd,inv(Trno1),1);

%% Passo 5 - Gerando as funções de pertinências contínuas

%% 
disp('');
disp('');
disp('');
disp('');
disp('------------------------------------------------------------------');
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
