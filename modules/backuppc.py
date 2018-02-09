import va_utils, salt, os.path, os, json, datetime, time, re, subprocess, fnmatch

from va_utils import check_functionality as panel_check_functionality
from va_backup_panels import panel

backuppc_dir = '/etc/backuppc/'
backuppc_pc_dir = '/etc/backuppc/'
backuppc_hosts = '/etc/backuppc/hosts'
sshcmd='ssh -oStrictHostKeyChecking=no root@'
rm_key='ssh-keygen -f "/var/lib/backuppc/.ssh/known_hosts" -R '

#Used when converting hash to json - replaces all instances of the first char with the second one. 
#Backslashes are a nightmare; json likes to have double backslashes. So we take any already double backslashes and reduce them by half, and then double all backslashes. 
hash_to_json_characters_map = [('\\\\', '\\'), ('\\', '\\\\'), ('\n', ''), ('=>', ':'), ('\'', '"'), (';', ','), ('=', ':')]
json_to_hash_characters_map = [(':', '=>'), (':','='), ('"', '\'')]


default_paths = {
    'va-monitoring' : ['/etc/icinga2', '/root/.va/backup', '/var/lib/pnp4nagios/perfdata/'],
    'va-directory' : ['/root/.va/backup', '/etc/openvpn'],
    'va-backup' : ['/etc/backuppc'],
    'va-fileshare' : ['/home', '/etc/samba'],
    'va-email' : ['/etc/postfix', '/root/.va/backup', '/var/vmail/'],
    'va-owncloud' : ['/root/.va/backup', '/var/www/owncloud'],
}

def host_file(hostname):
    filename = backuppc_dir+hostname+'.pl'
    return filename

#def get_panel(panel_name, host = '', backupNum = -1):
def get_panel(panel_name, server_name = '', backupNum = -1):
    host = server_name
    ppanel = panel[panel_name]
    hostnames = listHosts()
    if panel_name == "backup.hosts":
        ppanel['tbl_source']['table'] = panel_list_hosts()
        return ppanel
    elif panel_name == "backup.schedule":
        ppanel['tbl_source']['table'] = panel_list_schedule()
        return ppanel

    elif panel_name == "backup.manage":
        data  = panel_list_folders(hostnames)
#        data = [ {'app': key, 'path': v} for key,val in data.items() for v in val ]
        ppanel['tbl_source']['table'] = data
        return ppanel

    elif panel_name == "backup.browse":
        host = hostnames[0] if host == '' else host
        if backupNum == -1:
            backupNum = last_backup(host)
        data = dir_structure1(host, backupNum)
        ppanel['form_source'] = {"dropdown": {}};
        ppanel["form_source"]["dropdown"]["values"] = hostnames
        ppanel["form_source"]["dropdown"]["select"] = host
        ppanel['tbl_source']['table'] = data
        ppanel['tbl_source']['path'] = [host, backupNum]
        return ppanel

    elif panel_name == "backup.info":
        data = backup_info(host)
        ppanel['tbl_source']['table'] = data
        return ppanel

def dir_structure1(host, *args):
    check = False
    if len(args) == 0:
        backupNum = last_backup(host)
        attrib = backup_attrib(host, backupNum)
        check = True
    else:
        backupNum = args[0]
        attrib = backup_attrib(host, *args)
        args = args[1:]
    data = dir_structure(host, backupNum)
    if data == "No files available.":
        return []
    for x in args:
        data = data[x]
    result = []
    for key,val in data.items():
        type = 'folder' if val is not None else 'file'
        size = time = '/'
        if key in attrib:
            a = attrib[key]
            size, time = (a['size'], a['time'])
        if size != '/' and time != '/': 
            result.append({'dir': key, 'type': type, 'size': size, 'time': time});
    if check:
        return {'val': backupNum, 'list': result}
    [d.update({'size' : ''}) for d in result if d['type'] == 'folder']
    return result

def get_path_from_backup_number(hostname, backupnumber):
    path = '/var/lib/backuppc/pc/'+hostname+'/'+str(backupnumber)
    return path

def last_backup(host):
    result = map(int, backupNumbers(host))
    backupNum = max(backupNumbers(host))    
    return backupNum

def get_backup_pubkey():
    file_contents = ''
    with open('/var/lib/backuppc/.ssh/id_rsa.pub') as f:
        file_contents = f.read()
    return file_contents

def add_default_paths(hosts = []):
    for host in hosts:
        paths = [default_paths[x] for x in default_paths if __salt__['mine.get'](x, 'inventory')[x]['fqdn'] == host][0]
        for path in paths:
            result = add_folder(host, path)
    return True

def get_ip(hostname):
    hostname = hostname.lower()
    address = __salt__['mine.get']('fqdn:'+hostname,'address',expr_form='grain')
    try:
        address = address[address.keys()[0]][0]
    except: #TODO proper handling and / or get it from dns
        address = hostname

    return address

#Temporary functions
#TODO: remove all add_*_host wrappers and just use the original add_host() function. 
def add_smb_host(hostname, address, username, password):
    backup_arguments = {
        'SmbShareUserName' : username, 
        'SmbSharePasswd' : password, 
        'FullKeepCnt' : [30, 0, 0, 1, 1, 4, 3],
        'FullPeriod' : 0.97,
        'IncrPeriod' : 300, 
        'PingCmd' : '/bin/nc -z $host 445', 
        'XferMethod' : 'smb',
        'SmbShareName' : []
    }
    return add_host(hostname, address, 'smb', backup_arguments)

def add_rsync_host(hostname, address = None, password = None):
    backup_arguments = {
        'XferMethod' :'rsync',
        'RsyncShareName': []
    }
    if password: 
        putkey_windows(hostname, password)

    add_host(hostname, address, 'rsync', backup_arguments)

    __salt__['event.send']('backuppc/copykey', fqdn=hostname)
    __salt__['cmd.retcode'](cmd=rm_key+get_ip(hostname), runas='backuppc', shell='/bin/bash',cwd='/var/lib/backuppc')
    __salt__['cmd.retcode'](cmd=sshcmd+get_ip(hostname)+' exit', runas='backuppc', shell='/bin/bash',cwd='/var/lib/backuppc')


def add_archive_host(hostname):
    backup_arguments = {
        'XferMethod': 'archive'
    }
    return add_host(hostname, method = 'archive', backup_arguments = backup_arguments)

#backup_arguments is a list of whatever other arugments we want, for instance {"SmbSharePasswd" : "pass", "SmbShareUserName" : "backuppc", "DumpPreUserCmd" : "arg", "DumpPostUserCmd" : "arg"}}
def add_host(hostname, address=None, method='rsync', backup_arguments = {}):

    hostname = hostname.lower()
    if not address:
        address = get_ip(hostname) or hostname

    if not __salt__['file.file_exists'](host_file(hostname)):
        #If the file doesn't exist, we create the full file_data dict.
        file_data = backup_arguments

        file_data['ClientNameAlias'] = address 

        #Update backuppc folders
        __salt__['file.chown'](host_file(hostname), 'backuppc', 'www-data')
        __salt__['file.append'](backuppc_hosts, hostname+'       0       backuppc')

        #Finally, we convert the dict to a config file. 
        write_dict_to_conf(file_data, hostname)
    else:
        #TODO why is this even here? Looks like it should be in an edit_host function. 
        edit_conf_var(hostname, 'ClientNameAlias', str(address))
    
    __salt__['service.reload']('backuppc')

    return True



def rm_host(hostname):
    #To completely remove a client and all its backups, you should remove its entry in the conf/hosts file, and 
    #then delete the __TOPDIR__/pc/$host directory. Whenever you change the hosts file, you should send BackupPC a HUP (-1) signal
    # so that it re-reads the hosts file. If you don't do this, BackupPC will automatically re-read the hosts file at the next regular wakeup.
    hostname = hostname.lower()
    retcode = __salt__['file.remove'](host_file(hostname))
    __salt__['file.line'](path=backuppc_hosts,content=hostname+'.*backuppc', mode='delete')
    __salt__['file.chown'](backuppc_hosts, 'backuppc', 'www-data')
    __salt__['service.reload']('backuppc')
    return retcode

def add_folder(hostname, folder, backup_filter = ""):
    host_conf = conf_file_to_dict(hostname)
    hostname = hostname.lower()

    if folder[-1] == '/':
        folder = folder[:-1]
    if not __salt__['file.file_exists'](host_file(hostname)):
        return 'Host %s not found' % (hostname)
    if __salt__['file.search'](host_file(hostname),'\''+folder+'/?\''):
        return False

    method = get_host_protocol(hostname)
    new_folders = host_conf[method] + [folder]
    edit_conf_var(hostname, method, new_folders)

    if method == 'rsync':
        if __salt__['cmd.retcode'](cmd=sshcmd+get_ip(hostname)+' test ! -d '+folder, runas='backuppc', shell='/bin/bash',cwd='/var/lib/backuppc'):
            return True
        else:
            return False

    if backup_filter: 
        add_filter_to_path(hostname, folder, backup_filter)

    __salt__['service.reload']('backuppc')

def add_folder_list(hostname, folder_list,address,scriptpre="None",scriptpost="None",include=""):
    for folder in folder_list:
        add_folder(hostname=hostname,folder=folder,address=address,scriptpre=scriptpre,scriptpost=scriptpost,include=include)

def calculate_backup_periods(full_period, counters):
    if type(counters) != list: 
        counters = [counters]
    counters = [int(x) for x in counters]
    full_period = float(full_period)
    full_period = (int(full_period * 24.0) + 1 )/ 24.0
    periods = [0.0]
    for i in range(len(counters)):
        ctr = counters[i]
        period = 2 ** i * full_period
        for j in range(counters[i]):
            new_val = periods[-1] + period
            periods.append(new_val)

    periods = [round(x, 2) for x in periods[1:]]
    return periods


def pretty_backup_periods(full_period, counters):
    periods = calculate_backup_periods(full_period, counters)
    periods = ', '.join([str(x) for x in periods]) + ', '
    periods = periods.replace('.00', '')
    periods = periods.replace('.0, ', ', ')
    return periods


def get_filters_for_host(hostname, path):
    host_conf = conf_file_to_dict(hostname)
    backup_filters = host_conf.get('BackupFilesOnly', {})

    return backup_filters

def manage_host_filter(hostname, path, backup_filter, action = 'add'):
    if not backup_filter: 
        return

    backup_filters = get_filters_for_host(hostname, path)

    if action == 'add': 
        path_filters = backup_filters.get(path, []) + [backup_filter]
    elif action == 'remove' : 
        path_filters = [x for x in backup_filters.get(path, []) if x != backup_filter]

    else: 
        raise Exception('Invalid action in manage_host_filter: ' + str(action))

    backup_filters[path] = path_filters

    edit_conf_var(hostname, 'BackupFilesOnly', backup_filters)

def add_filter_to_path(hostname, path, backup_filter):
    return manage_host_filter(hostname, path, backup_filter, 'add')

def rm_filter_from_path(hostname, path, backup_filter):
    return manage_host_filter(hostname, path, backup_filter, 'remove')


def rm_folder(hostname, folder):
    hostname = hostname.lower()
    host_conf = conf_file_to_dict(hostname)
    method = get_host_protocol(hostname)
    if os.path.exists(host_file(hostname)):
        host_conf = conf_file_to_dict(hostname)
        host_folders = host_conf[method]
        host_folders = [x for x in host_folders if x != folder]

        edit_conf_var(hostname, method, host_folders)
        __salt__['file.chown'](host_file(hostname), 'backuppc', 'www-data')
        return 'Folder '+folder+' has been deleted from backup list'
    else:
        return 'Folder not in backup list'


def get_folders_from_config(hostname):
    conf_dir = host_file(hostname)
    host_protocol = get_host_protocol(hostname)

    host_config = conf_file_to_dict(hostname)
    folders = host_config.get(host_protocol, [])

    return folders
   

def list_folders(hostnames):
    folders_list = dict()
    if type(hostnames) == str:
        hostnames = [hostnames]
    for hostname in hostnames:
        folders = get_folders_from_config(hostname)
        folders_list[hostname] = folders
    return folders_list

def panel_list_folders(hostnames):
    data  = list_folders(hostnames)
    data = [ {'app': key, 'path': v, 'include' : find_matching_shares(key, v)} for key in data for v in data[key] ]
    return data

def listHosts():
    host_list = []
    with open(backuppc_hosts, "r") as h:
        for line in h:
            
            if '#' not in line and line != '\n':
                word = line.split()
                host_list.append(word[0])
    return host_list

def find_matching_shares(host, share_path):
    folders = []
    shares = conf_file_to_dict(host).get('BackupFilesOnly', [])
    for share in shares: 
        if fnmatch.fnmatch(share_path, share):
            folders += shares[share]
    return folders

def panel_list_hosts():
    host_list = listHosts()
    host_list = [{'host' : x, 'total_backups': backupTotals(x), 'protocol' : get_host_protocol(x).replace('ShareName', '')} for x in host_list]
    host_list = append_host_status(host_list)
    return host_list

def panel_list_schedule():
    host_schedule = listHosts()
    host_schedule = [{'host' : x, 'fullperiod': get_full_period(x), 'fullmax': get_full_max(x),'incrperiod': get_incr_period(x),'incrmax': get_incr_max(x)} for x in host_schedule]
    return host_schedule

def get_full_period(hostname):
    p = conf_file_to_dict(hostname).get('FullPeriod') or pretty_global_config('FullPeriod') + ' *'
    return p

def get_incr_period(hostname):
    p = conf_file_to_dict(hostname).get('IncrPeriod') or pretty_global_config('IncrPeriod')+" *"
    return p

def get_full_max(hostname):
    p = conf_file_to_dict(hostname).get('FullKeepCnt') or pretty_global_config('FullKeepCnt')+" *"
    return p

def get_incr_max(hostname):
 #   protocol = get_global_config('IncrKeepCnt', hostname) or "Global"
    p = conf_file_to_dict(hostname).get('IncrKeepCnt') or pretty_global_config('IncrKeepCnt')+" *"
    return p

def append_host_status(host_list):
    cmd = '/usr/share/backuppc/bin/BackupPC_serverMesg status hosts'
    text =  __salt__['cmd.run'](cmd, runas='backuppc')
    text = hashtodict(text)
    text = text.split('=')[1]
    text = text.replace(' undef' ,' \"undef\"')
    text = text.replace('Reason_' ,'')
    text = text.replace('\\', '\\\\')
    text = json.loads(text)

    for x in host_list:
        x['status'] = text[x['host']].get('reason', '-')
        x['status'] = x['status'].replace('_', ' ').capitalize()

        x['error'] = text[x['host']].get('error', "-").replace('_', ' ').capitalize()
    return host_list

def panel_statistics():
    cmd = '/usr/share/backuppc/bin/BackupPC_serverMesg status info'
    text =  __salt__['cmd.run'](cmd, runas='backuppc')
    text = hashtodict(text)
    text1 = hashtodict(text)
    text = text.split('=')[1]
    text = json.loads(text)
    i_version = text['Version']
    i_todaypool = text['DUDailyMax']
    i_yesterdaypool = text['DUDailyMaxPrev']
    i_folders = text['cpoolDirCnt']
    i_duplicates = text['cpoolFileCntRep']
    diskusage =__salt__['disk.usage']()[__salt__['cmd.run']('findmnt --target /var/lib/backuppc/ -o TARGET').split()[1]]
    statistics = [{'key' : 'Version', 'value': text['Version']},
                  {'key' : 'Files in pool', 'value': text['cpoolFileCnt']},
                  {'key' : 'Folders in pool', 'value': text['cpoolDirCnt']},
                  {'key' : 'Duplicates in pool', 'value': text['cpoolFileCntRep']},
                  {'key' : 'Nightly cleanup removed files', 'value': text['cpoolFileCntRm']},
                  {'key' : 'Pool partition used size (KB)', 'value': int(diskusage['used'])/1024},
                  {'key' : 'Pool partition free space (KB)', 'value': int(diskusage['available'])/1024},
                  {'key' : 'Pool partition mountpoint', 'value': diskusage['filesystem']},
                  {'key' : 'Pool usage now (%)', 'value': text['DUDailyMax']},
                  {'key' : 'Pool usage yesterday (%)', 'value': text['DUDailyMaxPrev']}]
    return statistics

def panel_default_config():
    cmd = 'cat /etc/backuppc/config.pl'
    text =  __salt__['cmd.run'](cmd)
    full_period = get_global_config('FullPeriod')
    full_cnt = get_global_config('FullKeepCnt')
    incr_period = get_global_config('IncrPeriod')
    incr_cnt = get_global_config('IncrKeepCnt')

    def_config = [{'key' : 'Full Backups period', 'value': full_period},
                  {'key' : 'Full Backups to keep (max)', 'value': full_cnt},
                  {'key' : 'Full Backups to keep (min)', 'value': get_global_config('FullKeepCntMin')},
                  {'key' : 'Full Backups sequence', 'value': pretty_backup_periods(full_period, full_cnt)},
                  {'key' : 'Remove Full Backups older then', 'value': get_global_config('FullAgeMax')},
                  {'key' : 'Incremental Backups period', 'value': get_global_config('IncrPeriod')},
                  {'key' : 'Incremental Backups to keep (max)', 'value': incr_period},
                  {'key' : 'Incremental Backups to keep (min)', 'value': incr_cnt},
                  {'key' : 'Incremental Backups sequence', 'value': pretty_backup_periods(incr_period, incr_cnt)},

                  {'key' : 'Remove incremental Backups older then', 'value': get_global_config('IncrAgeMax')}]
    return def_config



def get_global_config(item, hostname = 'config'):
    perl_simple_element = ['perl','-e', 'require "/etc/backuppc/%s.pl"; print $Conf{%s};' % (hostname, item)]
    perl_complex_element = ['perl', '-MJSON', '-e', 'require "/etc/backuppc/%s.pl"; $json_data = encode_json $Conf{%s}; print $json_data' % (hostname, item)]

    item = subprocess.check_output(perl_simple_element)
    if any([x in item for x in ['ARRAY', 'HASH']]):
        item = json.loads(subprocess.check_output(perl_complex_element))

    return item

def pretty_global_config(item, hostname = 'config'):
    value = get_global_config(item, hostname)
    if type(value) == list:
        value = ', '.join([str(x) for x in value])
    return value

    
def get_item_from_conf(item, hostname = 'config'):
    host_conf = host_file(hostname)
    with open(host_conf) as f:
       config = f.read()

    #you can probably do some more regexing to get perl values but this seems to work
    item_regex_comment_group = '(#.*)?'
    item_regex_var_definition = "\$Conf{%s}\s*=\s*" % item
    item_regex_value_characters = '([a-zA-Z\/0-9\.\,]*)'
    item_regex_value = "'?%s'?;" % item_regex_value_characters

    item_regex = item_regex_comment_group + item_regex_var_definition + item_regex_value
#    return item_regex
    item = re.findall(item_regex, config)
    item = [x[1] for x in item if '#' not in x[0]] or [None]

    if not item: 
        return None

    item = item[0]
    return item

def handle_vars(line):
    if len(line.split(' = ')) > 1:
        line = line.strip()
        return "'%s' = %s" % (line.split(' = ')[0], line.split(' = ')[1])
    return line

def handle_characters(conf, char_map = hash_to_json_characters_map):
    for pair in char_map:
        conf = conf.replace(pair[0], pair[1])
    return conf

def conf_to_json(conf):

    conf = conf.split('\n')
    conf = '\n'.join([handle_vars(x) for x in conf])
    conf = handle_characters(conf)

    conf = '{%s}' % (conf[:-1]) #[-1] to remove the final comma left after replacing ';' with ','
    conf = json.loads(conf)
    conf = {re.sub('\$Conf\{(.*)\}', '\g<1>', x) : conf[x] for x in conf} #Replace '$Conf{var}' with 'var' to make it more readable

    return conf

def dict_to_conf(json_data):
    json_data = '\n'.join(["$Conf{%s} = %s;" % (x, json.dumps(json_data[x])) for x in json_data])
    json_data = handle_characters(json_data, char_map = json_to_hash_characters_map)
    return json_data

def conf_file_to_dict(hostname):
    conf_file = host_file(hostname)
    with open(conf_file) as f:
        conf = f.read()

    conf = conf_to_json(conf)
    return conf

def write_dict_to_conf(data, hostname):
    data = dict_to_conf(data)
    conf_file = host_file(hostname)
    with open(conf_file, 'w') as f: 
        f.write(data)


def edit_conf_var(hostname, var, new_data, data_type = None):
    conf_data = conf_file_to_dict(hostname)

    if not new_data:
        if var in conf_data.keys():
            conf_data.pop(var)

    else:
        if data_type:
            try:
                if data_type == list: 
                    new_data = [x.strip() for x in new_data.split(',')]
                else:
                    new_data = data_type(new_data)
            except Exception as e:
                raise Exception("Error converting conf var " + str(new_data) + " to data_type " + str(data_type) + ": " + e.message)

        conf_data[var] = new_data
    return write_dict_to_conf(conf_data, hostname)


def change_fullperiod(hostname, new_data, var="FullPeriod"):
    return edit_conf_var(hostname, var, new_data, data_type = int)

def change_fullmax(hostname, new_data, var="FullKeepCnt"):
    return edit_conf_var(hostname, var, new_data, data_type = list)

def change_incrperiod(hostname, new_data, var="IncrPeriod"):
    return edit_conf_var(hostname, var, new_data, data_type = int)

def change_incrmax(hostname, new_data, var="IncrKeepCnt"):
    return edit_conf_var(hostname, var, new_data, data_type = list)

def reset_schedule(hostname):
    change_fullperiod(hostname, None)
    change_fullmax(hostname, None)
    change_incrperiod(hostname, None)
    change_incrmax(hostname, None)

def backupTotals(hostname):
    totalb = len(backupNumbers(hostname)) 
    return totalb


def get_host_protocol(hostname = 'config'):
    host_conf = conf_file_to_dict(hostname)
    method = host_conf.get('XferMethod') or get_global_config('XferMethod')
    method_vars = {
        'rsync' : 'RsyncShareName',
        'smb' : 'SmbShareName',
        'archive' : 'Archive',
    }
    protocol = method_vars[method]

    return protocol


def backupNumbers(hostname):
    hostname = hostname.lower()
    limit = re.compile("^[0-9]*$")
    hostname_path = '/var/lib/backuppc/pc/'+hostname+'/'
    if not os.path.isdir(hostname_path):
        return []

    dirs = [d for d in os.listdir(hostname_path) if os.path.isdir(os.path.join(hostname_path, d)) and limit.match(d)]
    return dirs

def backupFiles(hostname, number = -1):
    hostname = hostname.lower()
    if number == -1:
        result = map(int, backupNumbers(hostname))
        number = max(result)
        path = '/var/lib/backuppc/pc/'+hostname+'/'+ str(number) +'/'
    else :
        path = '/var/lib/backuppc/pc/'+hostname+'/'+ str(number) + '/'
    path = os.path.normpath(path)
    ffolders = []
    subfolders = []
    for root,dirs,files in os.walk(path, topdown=True):
        depth = root[len(path) + len(os.path.sep):].count(os.path.sep)
        if depth == 2:
            # We're currently two directories in, so all subdirs have depth 3
            subfolders += [os.path.join(root, d) for d in dirs]
            dirs[:] = [] # Don't recurse any deeper or comment this line for deeper
            # depth = root[len(path) + len(os.path.sep):].count(os.path.sep)
            # if depth == 3:
            #   subfolders += [os.path.join(root, d) for d in dirs]
            #   dirs[:] = []
    for value in subfolders:
        ffolders.append(value.replace('%2f','/'))
    return ffolders

def start_backup(hostname, tip='Full'):
    hostname = hostname.lower()
    if tip == 'Inc':
        tip = '0'
    elif tip == 'Full' or tip is None:
        tip = '1'
    cmd = '/usr/share/backuppc/bin/BackupPC_serverMesg backup '+hostname+' '+hostname+' backuppc '+tip
    return __salt__['cmd.run'](cmd, runas='backuppc')

def create_archive(hostname):
    protocol = get_host_protocol(hostname)
    if protocol == 'Archive' : 
        return "Cannot create archive on host %s: Protocol for the host is archive. " % (hostname)
    cmd = '/usr/share/backuppc/bin/BackupPC_archiveStart archive backuppc %s' % (hostname)
    result = __salt__['cmd.run'](cmd, runas = 'backuppc')
    return result

def putkey_windows(hostname, password, username='root', port=22):
    hostname = hostname.lower()
    cmd1 = 'sshpass -p '+password+' ssh-copy-id -oStrictHostKeyChecking=no '+username+'@'+hostname+ ' -p '+str(port)
    cmd = 'sshpass -p '+password+' ssh -oStrictHostKeyChecking=no '+username+'@'+hostname+ ' -p '+str(port)+' bash -l &'
    __salt__['cmd.run'](cmd, runas='backuppc')
    return __salt__['cmd.run'](cmd1, runas='backuppc')

def dir_structure(hostname, number = -1, rootdir = '/var/lib/backuppc/pc/'):
    hostname = hostname.lower()
    try:
        len(backupNumbers(hostname)) > 0
    except:
        return "No files available."
    hostname = hostname.lower()
    if len(backupNumbers(hostname)) == 0:
        rootdir = '/var/lib/backuppc/pc/'+hostname+'/'
    elif number == -1:
        result = map(int, backupNumbers(hostname))
        number = max(backupNumbers(hostname))
        rootdir = '/var/lib/backuppc/pc/'+hostname+'/'+str(number)+'/'
    else :
        rootdir = '/var/lib/backuppc/pc/'+hostname+'/'+str(number)+'/'
    dr = {}
    rootdir = rootdir.rstrip(os.sep)
    start = rootdir.rfind(os.sep) + 1
    struktura = os.walk(rootdir)

    def filter_f(name):
       BLACKLIST = ('attrib', 'backupInfo', 'backupInfo.json')
       if len(name) > 0 and name[0] == 'f' and name not in BLACKLIST: 
           return name[1:]
       else:
           return name

    for path, dirs, files in struktura:
        new_path = [filter_f(part) for part in path.split(os.sep)]
        path = os.sep.join(new_path)
        folders = path[start:].split(os.sep) # /pateka/vo/momentov
        subdir = {filter_f(a):None for a in files}
        parent = reduce(dict.get, folders[:-1], dr) # dr.get(folders[0]).get(folders[1]) ... roditelot
        parent[folders[-1]] = subdir # roditel[sin] = subdir

    if len(dr.keys()):
        first_key = dr.keys()[0]
        first_val = dr[first_key]
        if isinstance(first_val, dict):
            dr = first_val

    for key, val in dr.items():
        del dr[key]
        dr[key.replace('%2f', '/')] = val
    
    return dr

def hashtodict(contents):
    contents = contents.replace('=>', ':')
    contents = contents.replace('%','')
    contents = contents.replace('\'','\"')
    contents = contents.replace('(','{')
    contents = contents.replace(')','}')
    contents = contents.replace(';','')
    contents = contents.replace('backupInfo = ','')
    contents = contents.replace('\"fillFromNum\" : undef,','')
    return contents

def write_backupinfo_json(hostname, backup):
    hostname = hostname.lower()
    contents = ''
    path = get_path_from_backup_number(hostname, backup)
    with open(path + '/backupInfo','r+') as f:
        contents = f.read()
        contents = hashtodict(contents)
    with open(path + '/backupInfo.json', 'w') as f: 
        json.dumps(f.write(contents))
    
def backup_info(hostname):
    hostname = hostname.lower()
    backup_list = backupNumbers(hostname)
    content = []
    for backup in backup_list:
        info = {}
        write_backupinfo_json(hostname, str(backup))
        json_path = get_path_from_backup_number(hostname, backup)

        f = json.loads(open(json_path + '/backupInfo.json').read())
        for key in f:
            if key == "startTime":
                info.update({"startTime" : str(datetime.datetime.fromtimestamp(int(f["startTime"])).strftime('%Y-%m-%d %H:%M:%S')) })
            elif key == "endTime":
                info.update({"endTime" : str(datetime.datetime.fromtimestamp(int(f["endTime"])).strftime('%Y-%m-%d %H:%M:%S'))})
            elif key == "type":
                info.update({"type" : f["type"]})
            info.update({"duration" : str(datetime.timedelta(seconds = (int(f["endTime"]) - int(f["startTime"]))))})
            a = int(time.time()) - int(f["endTime"])
            m, s = divmod(a, 60)
            h, m = divmod(m, 60)
            d, h = divmod(h, 24)
            info.update({
                "age" : str("%d day(s) %d:%02d:%02d") % (d, h, m, s),
                "backup" : str(backup),
                "absolute_age" : str(a)
            })
        #info["age"] = str(datetime.timedelta(seconds = (int(time.time()) - int(f["endTime"]))))
        content.append(info)
        os.remove(json_path + '/backupInfo.json')
    content = sorted(content, key = lambda x: x['startTime'], reverse = True)
    return content

def tar_create(arguments, location='/usr/share', backupname='test_backup', backupnumber=-1):
    tar_create_cmd = '/usr/share/backuppc/bin/BackupPC_tarCreate -h '+arguments[0]+' -s '+arguments[1]+' -n '+str(backupnumber)+' '+arguments[2]+' > '+location+'/'+backupname+'.tar'
    return __salt__['cmd.run'](tar_create_cmd ,runas='backuppc', cwd='/var/lib/backuppc',python_shell=True)


#Example url
#http://10.0.10.45/index.cgi?action=RestoreFile&host=serversql&num=47&share=/cygdrive/c/db-dump&dir=/TEST_backup_2017_09_13_161329_0384659.fbak
#
def get_backuppc_url(hostname, backupnumber, share, path, action = 'RestoreFile', username = 'admin', password = '', instance_url = ''):
    kwargs = {
        'hostname' : hostname, 
        'backupnumber' : backupnumber, 
        'share' : share, 
        'path' : path, 
        'action' : action, 
        'username' : username,
    }

    kwargs['password'] = password or __salt__['pillar.get']('admin_password')
    kwargs['instance_url'] = instance_url or __salt__['network.ip_addrs']()[0]

    url = 'http://{username}:{password}@{instance_url}/index.cgi?action={action}&host={hostname}&num={backupnumber}&share={share}&dir={path}'

    url = url.format(**kwargs)
    return url


def download_zip(hostname, backupnumber = -1, share = '', path = '.', range_from = 0):
    zip_create_cmd = '/usr/share/backuppc/bin/BackupPC_zipCreate'
    p = subprocess.Popen(['sudo', '-u', 'backuppc', zip_create_cmd, '-h', hostname, '-n', str(backupnumber),
        '-s', share, ' ', path], stdout=subprocess.PIPE)
    BLOCK_SIZE = 10 ** 6
    has_read = 0
    while True:
        curr_out = p.stdout.read(BLOCK_SIZE)
        current_read = len(curr_out)
        has_read+= current_read
        if curr_out == '': return ''
        if has_read > range_from:
            return curr_out[range_from % BLOCK_SIZE:]

def restore_backup(hostname, backupnumber = -1, share = '',  path = '.', restore_host=''):
    if restore_host == '':
        restore_host=hostname
    tar_create_cmd = '/usr/share/backuppc/bin/BackupPC_tarCreate'
    args = ' -h '+hostname+' -n '+str(backupnumber)+' -s '+share+' '+path+' | ssh root@'+restore_host+' tar xf - -C '+share
    return __salt__['cmd.run'](tar_create_cmd+args,runas='backuppc', cwd = '/usr/lib/backuppc/',python_shell=True)

#This is a temporary 'hack', until we figure out what we really want to do. 
restore = restore_backup

#def restore(arguments, restore_host='', backupnumber=-1):
#    hostname = arguments[0]
#    share = arguments[1]
#    path = arguments[2]
#    return restore_backup(hostname, share, path, restore_host, backupnumber)

def infodict(path):
    contents = ''
    cmd = 'sudo -u backuppc /usr/share/backuppc/bin/BackupPC_attribPrint \'%s/attrib\' > \'%s/attrib0\'' % (path, path)
   # cmd = ['sudo -u ', 'backuppc', '/usr/share/backuppc/bin/BackupPC_attribPrint '+path+'/attrib', '>', path+'/attrib0'
    subprocess.call(cmd, shell = True)
    with open(path +'/attrib0','r+') as f:
        contents = f.read()
        contents = contents.replace('$VAR1 = {\n' , '{')
        contents = contents.replace('}\n}', '}}')
        contents = contents.replace('=>', ':')
        contents = contents.replace('%','')
        contents = contents.replace('\'','\"')
        contents = contents.replace('(','{')
        contents = contents.replace(')','}')
        contents = contents.replace(';','')

    contents = contents or '{}'
    with open(path+'/attrib.json', 'w') as f:
        json.dumps(f.write(contents))

def backup_attrib(hostname, number, *args):
    start = '/var/lib/backuppc/pc/'
    newshare ='empty'
    share = ''
    path = ''
    try:
        len(backupNumbers(hostname)) > 0
    except:
        return "No files available."
    if len(args) == 1:
        share = args[0]
        share = 'f' + share.replace('/','%2f')
        path = ''
    elif len(args) == 2:
        share = args[0]
        share = 'f' + share.replace('/','%2f')
        path = '/' + args[1]
        path = path.replace('/', '/f')
    infodict(start+hostname+'/'+str(number)+'/'+share+path)
    content = {}

    attrib_file = start + hostname + '/' + str(number) + '/' + share + path + '/attrib.json'
    with open(attrib_file) as f:
        f = f.read()
        f = json.loads(f)

    for key in f:
        name = key
        for keykey in f[key]:
            if keykey == 'mtime':
                time = datetime.datetime.fromtimestamp(int(f[key][keykey])).strftime('%Y-%m-%d %H:%M:%S')
            elif keykey == 'size':
                size = f[key][keykey]
        #info = { 'name' : name, 'time' : time, 'size' : size}
        content[name] = {'time' : time, 'size' : size}
    os.remove(start+hostname+'/'+str(number)+'/'+share+path+'/attrib.json')
    os.remove(start+hostname+'/'+str(number)+'/'+share+path+'/attrib0') 
    return content
