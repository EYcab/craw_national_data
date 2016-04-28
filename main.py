# -*- coding: utf-8' -*-
"""
Created on Apr 26 2016
@author:weiwu jiang
initial version from yiyuezhuo
"""
import requests
import time
import json
import os
import pandas as pd
import numpy as np
import pickle


def check_dir(name_list):
    if type(name_list) in [str,unicode]:
        name_list = name_list.replace('\\','/').split('/')
    now_path = name_list[0]
    for name in name_list[1:]:
        if not os.path.isdir(now_path):
            os.mkdir(now_path)
        now_path = os.path.join(now_path,name)


class TreeNode(object):
    url = 'http://data.stats.gov.cn/easyquery.htm'
    params = {'id':'zb','dbcode':'hgyd','name':'zb','wdcode':'zb','m':'getTree'}
    def __init__(self,iid='zb',name='zb',data_me=None,dbcodename='hgyd'):
        self.id = iid
        self.name = name
        self.data_me = None#Only leaf need this field
        self.data = None
        self.children = []
        self.leaf = None
        self.dbcode = dbcodename
    def get(self,force=False,verbose=True):
        if verbose:
            print 'getting',self.id,self.name
        if force or self.data==None:
            params = TreeNode.params.copy()
            params['id'] = self.id
            params['dbcode'] = self.dbcode
            res = requests.get(TreeNode.url,params=params)
            self.data = res.json()
            for data in self.data:
                self.children.append(TreeNode(iid=data['id'],name=data['name'],
                                              data_me=data))
            self.leaf = len(self.children)==0
    def get_recur(self,force=False,verbose=True):
        if force or self.data==None:
            self.get(verbose=verbose)
            for child in self.children:
                child.get_recur()
    def to_dict(self):
        children = [child.to_dict() for child in self.children]
        rd = self.data.copy()
        rd['children'] = children
        return rd
    def display(self,level=0):
        print ' '*level+self.name+' '+self.id
        for child in self.children:
            child.display(level+1)
    def get_all_pair(self):
        if self.leaf:
            return [(self.id,self.name)]
        else:
            rl = []
            for child in self.children:
                rl.extend(child.get_all_pair())
            return rl



class Downloader(object):
    def __init__(self,tree,raw_root='raw',date='1978-2014'):
        self.tree = tree
        self.map_name = dict(tree.get_all_pair())
        self.map_json = {}
        self.raw_root = raw_root
        self.date = date
    def get_params(self,valuecode):
        params = {'m':'QueryData','dbcode':'hgyd',
                'rowcode':'zb','colcode':'sj',
                'wds':[],
                'dfwds':[{'wdcode':'zb','valuecode':None},
                         {'wdcode':'sj','valuecode':self.date}],
                'k1':None}
        # requests can't deal tuple,list,dict correctly,I transform
        #them to string and replace ' -> " to solve it
        params['dfwds'][0]['valuecode']=str(valuecode)#Shocked!requests can't handle unicode properly
        params['k1'] = int(time.time()*1000)
        rp = {key:str(value).replace("'",'"') for key,value in params.items()}
        return rp
    def download_once(self,valuecode,to_json=False):
        url = 'http://data.stats.gov.cn/easyquery.htm'
        params = self.get_params(valuecode)
        res=requests.get(url,params=params)
        if to_json:
            return res.json()
        else:
            return res.content
    def valuecode_path(self,valuecode):
        return os.path.join(self.raw_root,valuecode)
    def cache(self,valuecode,content):
        f = open(self.valuecode_path(valuecode),'wb')
        f.write(content)
        f.close()
    def is_exists(self,valuecode,to_json=False):
        if to_json:
            return self.map_json.has_key(valuecode)
        else:
            path = os.path.join(self.raw_root,valuecode)
            return os.path.isfile(path)
    def download(self,verbose=True,to_json=False):
        length = len(self.map_name)
        for index,valuecode in enumerate(self.map_name.keys()):
            if verbose:
                print 'get data',valuecode,self.map_name[valuecode],'clear',float(index)/length
            if not self.is_exists(valuecode,to_json=to_json):
                res_obj = self.download_once(valuecode,to_json=to_json)
                if to_json:
                    self.map_json[valuecode]=res_obj
                else:
                    self.cache(valuecode,res_obj)

class Document(object):
    def __init__(self,raw_root='raw'):
        self.raw_root = raw_root
    def get(self,name):
        path = os.path.join(self.raw_root,name)
        with open(path,'rb') as f:
            content = f.read()
        return content
    def get_json(self,name):
        return json.loads(self.get(name))
    def json_to_dataframe(self,dic,origin_code=True):
        assert dic['returncode']==200
        returndata=dic['returndata']
        datanodes,wdnodes = returndata['datanodes'],returndata['wdnodes']
        if not origin_code:#parse wdnodes for transform that
            wd = {w['wdcode']:{ww['code']:ww['cname'] for ww in w['nodes']} for w in wdnodes}
            zb_wd,sj_wd = wd['zb'],wd['sj']
        rd = {}
        for node in datanodes:
            sd = {w['wdcode']:w['valuecode'] for w in node['wds']}
            zb,sj = sd['zb'],sd['sj']
            if not origin_code:
                zb,sj = zb_wd[zb],sj_wd[sj]
            rd[(sj,zb)] = node['data']['data'] if node['data']['hasdata'] else np.NaN
        df = pd.Series(rd).unstack()
        df = df.transpose().sort_index(axis=1,ascending=False)
        return df
    def get_dataframe(self,name,origin_code=False):
        return self.json_to_dataframe(self.get_json(name),origin_code=False)
    def to_file(self,name,path,encoding='utf8'):
        df = self.get_dataframe(name)
        df.to_csv(path,encoding=encoding)
        df.to_excel(path.replace('.csv','.xlsx'))
    def iter_tree(self,tree,path=('zb',),origin_dir=False):
        yield path,tree
        for node in tree.children:
            newpath = path+((node.id,) if origin_dir else (node.name,))
            for r in self.iter_tree(node,path=newpath):
                yield r
    def to_file_all(self,tree,root='data',encoding='utf8'):
        for path,node in self.iter_tree(tree):
            if node.leaf:
                path_t = (root,)+path
                check_dir(path_t)
                self.to_file(node.id,os.path.join(*path_t)+'.csv',encoding=encoding)

if __name__ == "__main__":
    print '''国家数据(国家统计局)抓取器加强版/This toolkit could automatically download data from National data base. '''
    querytype = ''
    while not(querytype == '1' or querytype == '2' or querytype == '3'):
         print '''请输入查询数据种类/Please input the type of query:
        1--月度数据/monthly  2--季度数据/seasonly  3--年度数据/yearlly'''
         querytype = raw_input()
    querystarttime = ''
    while not len(querystarttime) == 4:
        print '''请输入查询的起始年份（四位数）/Please input the start year of query (4 digits):'''
        querystarttime = raw_input()
    queryendtime = 'x'
    while not (len(queryendtime) == 4 or len(queryendtime) == 0):
        print '''请输入查询的结束年份（四位数，空输入表示最新的年份）/Please input the end year of query (4 digits,Empty Input for the latest year):'''
        queryendtime = raw_input()

    querytime = querystarttime + '-' + queryendtime
    savefoldname = 'data'
    dbcodename = 'hgyd'
    if(querytype == '1'): #'hgyd'-->月度
        dbcodename = 'hgyd'
        savefoldname = 'Monthly'
    elif(querytype == '2'): #'hgjd'-->季度
        dbcodename = 'hgjd'
        savefoldname = 'Seasonly'
    else:  #'hgnd'--》年度
        dbcodename = 'hgnd'
        savefoldname = 'Yearly'

    tree=TreeNode()
    tree.get_recur()
    with open('tree','wb') as f:
        pickle.dump(tree,f)

    with open('tree','rb') as f:
        tree=pickle.load(f)

    downloader=Downloader(tree,raw_root='temp',date=querytime)
    downloader.download()
    doc=Document(raw_root='temp')
    doc.to_file_all(tree,root=savefoldname,encoding='utf-8')

    print '''Finished!'''
    raw_input()









