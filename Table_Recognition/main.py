import torch
import tfrecord
import numpy as np
import os
import pickle

from tfrecord.torch.dataset import TFRecordDataset

from utils import get_all_targets, get_stats, tfrecord_preparer
from feature_CNN import FeatureNet_v1
from GCNN import SimpleNet,FullyConnectNet
from Vex_Mout import VexMoutNet
import config
from tqdm import tqdm


from time import process_time

"Very early version of main loop. Testing imports and pipeline atm."

#processed_
#Load list of tfRecords from folder: 
Train_path = os.getcwd()+r'\Table_Recognition\Data\Train'
Val_path = os.getcwd()+r'\Table_Recognition\Data\Val'

#OBS test data is currently not in use
Test_path = os.getcwd()+r'\Table_Recognition\Data\Test'


#######################################################################################################
########################################### Params ####################################################
#######################################################################################################
batch_size = 16

device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')

num_epochs = 20

prediction_thres = 0.5


#######################################################################################################
########################################### Load models ###############################################
#######################################################################################################

#load Feature CNN model
featurenet_path = os.getcwd()+r"\Table_Recognition\models\FeatureNet_v1.pt"
featurenet = FeatureNet_v1()
featurenet.load_state_dict(torch.load(featurenet_path,map_location=torch.device('cpu')))
featurenet.eval()




#######################################################################################################
######################################## Define Model Elements ########################################
#######################################################################################################




model = VexMoutNet()


# move model to the right device
model.to(device)

#stats of previous training. loss decay + f1 development
Stats = dict()
Stats['total_loss'] = []
Stats['loss_cells'] = []
Stats['loss_cols'] = [] 
Stats['loss_rows'] = []
Stats['f1_cells'] = []
Stats['f1_cols'] = []
Stats['f1_rows'] = []


# construct an optimizer
params = [p for p in model.parameters() if p.requires_grad]
optimizer = torch.optim.SGD(params, lr=0.001,
                            momentum=0.9, weight_decay=0.01)
# and a learning rate scheduler

'''
lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer,
                                                step_size=3,
                                                gamma=0.1)
                                                
'''


#######################################################################################################
########################################### Training Loop #############################################
#######################################################################################################



for epoch in range(num_epochs):
    train_loss = 0
    val_loss = 0 
    ct_train = 0
    ct_val = 0


    model.train()
    #load filenames of folder: 
    tfrecord_files = os.listdir(Train_path)
    loop = tqdm(enumerate(tfrecord_files), total=len(tfrecord_files))
    for idx, record in loop:

        tfrecord_path = os.path.join(Train_path,record)
        dataset = TFRecordDataset(tfrecord_path, config.index_path, config.tfrecord_description)
        loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size)
        
        for batch in loader:
            ct_train+=1
            data_dict = tfrecord_preparer(batch,device=device, batch_size=batch_size)

            optimizer.zero_grad()
            
            loss_cells, loss_cols, loss_rows, stat_dict = model(data_dict, device, prediction_thres)
            
            total_loss = loss_cells + loss_cols + loss_rows 
            
            total_loss.backward()
            optimizer.step()
            #lr_scheduler.step()
            train_loss+=total_loss.item()

            loop.set_description(f'Train Epoch [{epoch+1}/{num_epochs}]')
            loop.set_postfix_str(s=f"Total_loss = {round(total_loss.item(),4)}, Cells = {round(loss_cells.item(),4)}, Cols = {round(loss_cols.item(),4)}, Rows = {round(loss_rows.item(),4)}, F1_Cells = {round(stat_dict['cells']['f1'],4)}, F1_Cols = {round(stat_dict['cols']['f1'],4)}, F1_Rows = {round(stat_dict['rows']['f1'],4)}")
    
    #torch.cuda.empty_cache()
    model.eval()
    tfrecord_files = os.listdir(Val_path)

    validation_batch_size = 4
    loop = tqdm(enumerate(tfrecord_files), total=len(tfrecord_files))
    
    for idx, record in loop:
        tfrecord_path = os.path.join(Val_path,record)
        #Maybe tfrecords need to be generated with more files, to make loading more effective? 
        dataset = TFRecordDataset(tfrecord_path, config.index_path, config.tfrecord_description)
        loader = torch.utils.data.DataLoader(dataset, batch_size=validation_batch_size)
        for batch in loader:
            ct_val+=1
            data_dict = tfrecord_preparer(batch,device=device,batch_size=validation_batch_size)
            
            preds_dict = model(data_dict,device, prediction_thres)
            

            targets_cells, targets_cols, targets_rows = get_all_targets(data_dict)
           
            temp_pos_weight = torch.tensor([1])
            loss_cells = model.head_loss(preds_dict['cells'].reshape(-1),targets_cells.to(device),temp_pos_weight.to(device))
            loss_cols =  model.head_loss(preds_dict['cols'].reshape(-1),targets_cols.to(device),temp_pos_weight.to(device))
            loss_rows = model.head_loss(preds_dict['rows'].reshape(-1),targets_rows.to(device),temp_pos_weight.to(device))
            total_loss = loss_cells+loss_cols+loss_rows
           
            for k,v in preds_dict.items():
                preds_dict[k] = v.to(torch.device('cpu'))

            val_loss+=total_loss.item()
            
            stat_dict = get_stats(preds_dict['cells'],preds_dict['cols'],preds_dict['rows'],targets_cells,targets_cols,targets_rows,prediction_thres)
            

            #Iterate over, put tensors to device
            loop.set_description(f'Val Epoch [{epoch+1}/{num_epochs}]')
            loop.set_postfix_str(s=f"Total_loss = {round(total_loss.item(),4)}, Cells = {round(loss_cells.item(),4)}, Cols = {round(loss_cols.item(),4)}, Rows = {round(loss_rows.item(),4)}, F1_Cells = {round(stat_dict['cells']['f1'],4)}, F1_Cols = {round(stat_dict['cols']['f1'],4)}, F1_Rows = {round(stat_dict['rows']['f1'],4)}")
    print(f"#####AVERAGE: Epoch [{epoch+1}/{num_epochs}] Train Loss: {train_loss/ct_train}, Val Loss: {val_loss/ct_val}####################")
    if idx % 100 == 0:
        Stats['total_loss'].append(total_loss)
        Stats['loss_cells'].append(loss_cells)
        Stats['loss_cols'].append(loss_cols)   
        Stats['loss_rows'].append(loss_rows)
        Stats['f1_cells'].append(stat_dict['cells']['f1'])
        Stats['f1_cols'].append(stat_dict['cols']['f1'])
        Stats['f1_rows'].append(stat_dict['rows']['f1'])


#GEM MODEL OGSÅ!!!
torch.save(model.state_dict(), os.getcwd()+r'\Table_Recognition\model.pt')


with open(os.getcwd()+r'\Table_Recognition\Stats.pickle', 'wb') as handle:
    pickle.dump(Stats, handle, protocol=pickle.HIGHEST_PROTOCOL)