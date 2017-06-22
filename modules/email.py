import subprocess, re

panel = {"email.user":{"title":"List users","tbl_source":{"table":{}},"content":[{"type":"Table","name":"table","reducers":["table","panel","alert"],"columns":[{"key":"user","label":"User"},{"key":"action","label":"Actions"}],"source":"list_users","panels":{"list_rules":"email.rules"},"actions":[{"action":"list_rules","name":"List rules"}],"id":["user"]}]},"email.rules":{"title":"List rules","tbl_source":{"table":{}},"content":[{"type":"Table","name":"table","reducers":["table","panel","alert","modal"],"columns":[{"key":"rule","label":"Rule"},{"key":"action","label":"Actions"}],"source":"list_rules","modals":{"add_rule":{"title":"Add rule","buttons":[{"type":"Button","name":"Cancel","action":"cancel"},{"type":"Button","name":"Add","class":"primary","action":"add_rule"}],"content":[{"type":"Form","name":"form","class":"left","elements":[{"type":"text","name":"Rule","value":"","label":"Rule","required":True}]},{"type":"Div","name":"div","class":"right","elements":[{"type":"Heading","name":"Fill the form to change rule for user"},{"type":"Paragraph","name":"The changed data for user will be automatically synchronized with Email server."}]}]}},"actions":[{"action":"rm_rule","name":"Remove"},{"action":"add_rule","name":"Add rule"}],"id":["rule"]}]}}

def get_panel(panel_name, user = ''):
    ppanel = panel[panel_name]
    if panel_name == "email.user":
        data = [ {'user': x} for x in list_users() ]
        ppanel['tbl_source']['table'] = data
    if panel_name == "email.rules":
        data = get_user_rules(user)
        data = [ {'rule': x} for x in data]
        ppanel['tbl_source']['table'] = data
    return ppanel

#These functions are mostly for helping the actual functions work. YOu can still use them but yeah. 

def postmap_user(user):
    postmap_cmd = ['postmap', '%s' % user]
    subprocess.check_output(postmap_cmd)

def reload_postfix():
    postfix_cmd = ['service', 'postfix', 'reload']
    subprocess.check_output(postfix_cmd)

def touch_file(file_path):
    open(file_path, 'a').close()

def change_postfix_restriction(user, action = 'add'):
    main = ''
    with open('/etc/postfix/main.cf') as f:
        main = f.read()

    user_restriction_line = '%s =\n    check_recipient_access hash:/etc/postfix/local_domains, reject' % user

    if action == 'add':
        main = re.sub("(smtpd_restriction_classes = .*)", '\\1, %s\n\n%s' % (user, user_restriction_line), main)
    elif action == 'rm':
        main = re.sub("(smtpd_restriction_classes = .*)(, %s)(.*)" % user, '\\1\\3', main)
        main = re.sub('\n' + user + ' =.*\n.*\n', '', main)


    with open('/etc/postfix/main.cf', 'w') as f:
        f.write(main)

def add_recipient_line(user, recipient):
    with open('/etc/postfix/%s' % user, 'a') as f:
        f.write('\n%s OK' % recipient)


def rm_recipient_line(user, recipient):
    rules = ''
    with open('/etc/postfix/' + user, 'r') as f: 
        rules = f.read()
        

    rules = re.sub(recipient + '.*', '', rules)

    with open('/etc/postfix/' + user, 'w') as f: 
        f.write(rules)

#Above functions are mostly for helping with the actual functions. Those are the ones below.

def add_email_user_restriction(user):
    user_file_path = '/etc/postfix/' + user
    print 'Touching : ', user_file_path
    touch_file(user_file_path)
#    postmap_user(user)
    change_postfix_restriction(user, action = 'add')
#    reload_postfix()

def rm_email_user_restriction(user):
    touch_file('/etc/postfix/%s' % user)
#    postmap_user(user)
    change_postfix_restriction(user, action = 'rm')
#    reload_postfix()

def add_user_recipient(user, recipient):
    add_recipient_line(user, recipient)

#    postmap_user(user)
    reload_postfix()

def rm_user_recipient(user, recipient):
    rm_recipient_line(user, recipient)

#    postmap_user(user)
    reload_postfix()

def list_users():
    users = ['test1', 'test3', 'test4', 'test5']
    return users

def get_user_rules(user):
    user = user.replace('@', '.')
    rules = ''
    with open('/etc/postfix/' + user) as f:
        rules = f.read()
    rules = rules.split('\n')
    rules = [x.split(' ')[0].split('\t')[0] for x in rules if x]
    return rules

def list_users():
    users = ['test1@kam.com.mk', 'test2@kam.com.mk']
    return users