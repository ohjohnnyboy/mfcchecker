from ws4py.client.threadedclient import WebSocketClient
from sys import stdout
import threading
import json
import time, datetime
from random import randint
from subprocess import call
import sqlite3
from os import path
from urllib2 import unquote


def enum(**enums):
    return type('Enum', (), enums)

APPLICATION_DATABASE=path.dirname(path.realpath(__file__))+"/mfc_checker.db"

class Logger:

    LOG_LEVELS=enum(
            TRACE = 10,
            DEBUG = 20,
            INFO = 30,
            WARN = 40,
            ERROR = 50,
            FATAL = 100,
            FORCE = 999)
    LOG_LEVEL_LABEL = {
            LOG_LEVELS.TRACE : "Trace",
            LOG_LEVELS.DEBUG : "Debug",
            LOG_LEVELS.INFO : "Info",
            LOG_LEVELS.WARN : "Warn",
            LOG_LEVELS.ERROR : "Error",
            LOG_LEVELS.FATAL : "Fatal",
            LOG_LEVELS.FORCE : ""
            }

    def __init__(self,log_level=LOG_LEVELS.INFO, desktop_notifications_activated=True, show_user_input_prompt=False):
        self.log_level=log_level
        self.desktop_notifications_activated=desktop_notifications_activated
        self.show_user_input_prompt=show_user_input_prompt

    def printline(self,string, desktop_notify=False, log_level=LOG_LEVELS.INFO):
        if log_level < self.log_level:
            return

        log_level_label = Logger.log_level_label(log_level)
        if log_level_label != "":
            log_level_label=" - "+log_level_label

        msg="["+datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')+log_level_label+"] "+string
        if self.show_user_input_prompt:
            print

        print(msg)

        if self.show_user_input_prompt:
            stdout.write(">> ")
            stdout.flush()
        if desktop_notify and self.desktop_notifications_activated:
            summary="MFC online checker"
            body=string
            call(["notify-send", summary, body])

    @staticmethod
    def log_level_label(level):
        try:
            label = Logger.LOG_LEVEL_LABEL[level]
        except KeyError:
            label = ""
        return label

class MFCModel:
    def __init__(self,name):
        self.name = name
        self.isOnline = False
        self.isMuted = False
        self.isChecked = False

    def __str__(self):
        string = self.name
        if self.isMuted:
            string += " (muted)"
        return string

class MFCClient(WebSocketClient):

    STATUS_CODES=enum(
            FCVIDEO_TX_IDLE = 0,
            FCVIDEO_TX_RESET = 1,
            FCVIDEO_TX_AWAY = 2,
            FCVIDEO_TX_CONFIRMING = 11,
            FCVIDEO_TX_PVT = 12,
            FCVIDEO_TX_GRP = 13,
            FCVIDEO_TX_KILLMODEL = 15,
            FCVIDEO_RX_IDLE = 90,
            FCVIDEO_RX_PVT = 91,
            FCVIDEO_RX_VOY = 92,
            FCVIDEO_RX_GRP = 93,
            FCVIDEO_UNKNOWN = 127)

    sessionId = ""
    models=[]
    desktop_notify_enabled=True
    display_transition_to_offline=True

    def opened(self):
        self.send("hello fcserver\n\0")
        self.send("1 0 0 1 0 guest:guest\n\0")

    def closed(self, code, reason=None):
        LOGGER.printline("Websocket closed", log_level=Logger.LOG_LEVELS.DEBUG)

    def received_message(self, m):
        msg=m.data[4:]
        msgs=msg.split(' ')
        msg_type = msg_from = msg_to = msg_arg1 = msg_arg2 = msg_data = ""
        if len(msgs) >= 5:
            msg_type = msgs[0]
            msg_from = msgs[1]
            msg_to   = msgs[2]
            msg_arg1 = msgs[3]
            msg_arg2 = msgs[4]
        if len(msgs) > 5:
            msg_data = unquote(' '.join(msgs[5:]))

        LOGGER.printline("Received: "+m.data, log_level=Logger.LOG_LEVELS.DEBUG)
        LOGGER.printline("Message: "+msg_type, log_level=Logger.LOG_LEVELS.DEBUG)
        LOGGER.printline("From: "+msg_from, log_level=Logger.LOG_LEVELS.DEBUG)
        LOGGER.printline("To: "+msg_to, log_level=Logger.LOG_LEVELS.DEBUG)
        LOGGER.printline("Arg1: "+msg_arg1, log_level=Logger.LOG_LEVELS.DEBUG)
        LOGGER.printline("Arg2: "+msg_arg2, log_level=Logger.LOG_LEVELS.DEBUG)
        LOGGER.printline("Data: "+msg_data, log_level=Logger.LOG_LEVELS.DEBUG)

        if msg_type == "1":
            self.sessionId = msg_to
            LOGGER.printline("Logged in "+self.sessionId, log_level=Logger.LOG_LEVELS.DEBUG)
            self._check()
            return
            
        if msg_data != "":
            for i in self._getJsonPartsFromData(msg_data):
                try:
                    data_json=json.loads(i)
                    LOGGER.printline(json.dumps(data_json, sort_keys=True, indent=4, separators=(',', ': ')), log_level=Logger.LOG_LEVELS.DEBUG)
                except ValueError:
                    LOGGER.printline("Error decoding received message from MFC: "+i, log_level=Logger.LOG_LEVELS.ERROR)
                    continue

                model_name=data_json["nm"]
                model_status=data_json["vs"]
                model = self.getModel(model_name)
                if not model:
                    LOGGER.printline("Unexpected MFC response (unrequested model name): "+model_name,log_level=Logger.LOG_LEVELS.ERROR)
                    return

                if model_status == MFCClient.STATUS_CODES.FCVIDEO_TX_IDLE:
                    if not model.isOnline:
                        model.isOnline = True
                        if not model.isMuted:
                            LOGGER.printline("Model "+model.name+" is now online", desktop_notify=self.desktop_notify_enabled, log_level=Logger.LOG_LEVELS.INFO)
                else:
                    if model.isOnline:
                        model.isOnline = False
                        if self.display_transition_to_offline:
                            if not model.isMuted:
                                if model_status == MFCClient.STATUS_CODES.FCVIDEO_UNKNOWN:
                                    LOGGER.printline("Model "+model.name+" has gone offline", desktop_notify=self.desktop_notify_enabled, log_level=Logger.LOG_LEVELS.INFO)
                                else:
                                    LOGGER.printline("Model "+model.name+" has gone in limbo", desktop_notify=self.desktop_notify_enabled, log_level=Logger.LOG_LEVELS.INFO)
                    else:
                        if not model.isMuted and not model.isChecked and model_status != MFCClient.STATUS_CODES.FCVIDEO_UNKNOWN:
                            LOGGER.printline("Model "+model.name+" is in limbo", desktop_notify=self.desktop_notify_enabled, log_level=Logger.LOG_LEVELS.INFO)
                model.isChecked = True

    def getModel(self,model_name):
        return next((model for model in self.models if model.name==model_name), None)

    def check_consistency(self):
        for model in filter(lambda x: not x.isChecked, self.models):
            LOGGER.printline("It seems that model "+model.name+" does not exist", desktop_notify=self.desktop_notify_enabled, log_level=Logger.LOG_LEVELS.WARN)

    def _heartbeat(self):
        threading.Timer(10.0, self.heartbeat).start()
        if self.sessionId != "":
            LOGGER.printline("Send hartbeat "+self.sessionId, log_level=Logger.LOG_LEVELS.DEBUG)
            self.send("0 "+self.sessionId+" 0 0 0\n\0")

    def _check(self):
        # could possibly change this to only send requests for not muted models (and remove the test on isMuted in the response handling)
        for model in self.models:
            LOGGER.printline("Send info request for model "+str(model), log_level=Logger.LOG_LEVELS.DEBUG)
            self.send("10 "+self.sessionId+" 0 20 0 "+model.name+"\n\0")

    def _getJsonPartsFromData(self,data):
        count=0
        startIdx=-1
        result=[]
        for i, ch in enumerate(data, start=0):
            if ch == "{":
                if startIdx == -1:
                    startIdx=i
                count += 1
            elif ch == "}":
                count -= 1
                
            if count <= 0 and startIdx != -1:
                result.append(data[startIdx:i+1])
                startIdx=-1
        return result

class MainApplication(threading.Thread):

    WEBSOCKET_SERVERS=[
            "xchat7",
            "xchat8",
            "xchat9",
            "xchat10",
            "xchat11",
            "xchat12",
            "xchat20"
    ];

    def __init__(self):
        threading.Thread.__init__(self)
        self.db_connector = ApplicationDatabaseConnector(APPLICATION_DATABASE)
        self.models=map(lambda x: MFCModel(x),self.db_connector.get_models())
        self.checking_interval=self.db_connector.retrieve_default_value("CHECKING_INTERVAL")
        self.initial_dektop_notify_enabled=self.db_connector.retrieve_default_value("DESKTOP_NOTIFICATIONS_INITIAL")
        self.display_transition_to_offline=self.db_connector.retrieve_default_value("SHOW_TRANSITION_TO_OFFLINE")

        self.ws = None
        self.first =True
        self.stopped=False

    def run(self):
        while not self.stopped:

            if self.ws is None:
                self.displayModelsToCheck(log_level=Logger.LOG_LEVELS.INFO)
            else:
                self.models = self.ws.models
                self.ws.close()
                self.displayStatus(log_level=Logger.LOG_LEVELS.DEBUG)

            url = 'ws://'+MainApplication.WEBSOCKET_SERVERS[randint(0,len(MainApplication.WEBSOCKET_SERVERS)-1)]+'.myfreecams.com:8080/fcsl'
            LOGGER.printline("Connecting to "+url, log_level=Logger.LOG_LEVELS.DEBUG)

            self.ws = MFCClient(url, protocols=['http-only', 'chat'])
            self.ws.models=self.models
            if self.first and not self.initial_dektop_notify_enabled:
                self.ws.desktop_notify_enabled = False
            self.ws.display_transition_to_offline=self.display_transition_to_offline

            start_connect=time.time()
            self.ws.connect()
            self.ws.run_forever()
            self.ws.desktop_notify_enabled = True

            if self.first:
                self.ws.check_consistency()
                self.first=False

            duration_connect=time.time()-start_connect
            LOGGER.printline("Sleeping "+str(self.checking_interval-duration_connect)+" (start: "+str(start_connect)+" , duration: "+str(duration_connect)+") if not interrupted ("+str(self.stopped)+")", log_level=Logger.LOG_LEVELS.DEBUG)
            while not self.stopped and duration_connect < self.checking_interval:
                time.sleep(0.5)
                duration_connect=time.time()-start_connect

    def stopApplication(self): 
        if self.ws is not None:
            self.ws.close()
        if self.db_connector is not None:
            self.db_connector.close()
        self.stopped=True

    def recheckConsistency(self):
        self.ws.check_consistency()

    def displayStatus(self,log_level=Logger.LOG_LEVELS.INFO):
        LOGGER.printline("All online models: "+", ".join(map(str,filter(lambda x: x.isOnline,self.models))), log_level=log_level)
        LOGGER.printline("All offline models: "+", ".join(map(str,filter(lambda x: not x.isOnline,self.models))), log_level=log_level)

    def displayModelsToCheck(self,log_level=Logger.LOG_LEVELS.INFO):
        LOGGER.printline("All models to check: "+", ".join(map(str,self.models)), log_level=log_level)

    def getModel(self,model_name):
        return self.ws.getModel(model_name)

class UserCommandProcessor:

    USER_COMMANDS_LABELS = enum(
            LIST = "LIST")
    USER_COMMANDS = {
            USER_COMMANDS_LABELS.LIST: {
                "description": "List the available user commands",
                "fct": "_execute_list" }
            }

    def __init__(self):
        self._configureCommands()

    def _configureCommands(self):
        raise NotImplementedError("The concrete implementation of UserCommandProcessor should implement the method _configureUserCommands to add application specific user commands")

    def _addCommands(self,commandMap):
        self.USER_COMMANDS.update(commandMap)

    def execute(self,command):
        LOGGER.printline("Executing user command "+command,log_level=Logger.LOG_LEVELS.DEBUG)
        commands = self._sanitizeCommand(command)
        if commands is None or len(commands) == 0 or commands[0] == "":
            return

        LOGGER.printline("Sanitized command "+','.join(commands),log_level=Logger.LOG_LEVELS.DEBUG)
        try:
            fct = getattr(self,self.USER_COMMANDS[commands[0]]["fct"])
        except Exception:
            LOGGER.printline("Unknown command "+command,log_level=Logger.LOG_LEVELS.ERROR)
            return

        LOGGER.printline("Function to execute: "+str(fct),log_level=Logger.LOG_LEVELS.DEBUG)
        try:
            if len(commands) > 1:
                LOGGER.printline("Executing function with following parameters: "+", ".join(commands[1:]),log_level=Logger.LOG_LEVELS.DEBUG)
                fct(commands[1:])
            else:
                fct()
        except TypeError:
            LOGGER.printline("Missing argument or incorrect number of arguments for command",log_level=Logger.LOG_LEVELS.ERROR)

    def _sanitizeCommand(self,command):
        commands=command.split(' ')
        if commands is None or len(commands) == 0 or commands[0] == "":
            return None
        commands[0]=commands[0].upper()
        return commands

    def _execute_list(self):
        text="\n"
        for c, props in sorted(self.USER_COMMANDS.iteritems()):
            text+="    "+c.lower().ljust(10)+" : "+props["description"]+"\n"
        LOGGER.printline("Available user commands:"+text,log_level=Logger.LOG_LEVELS.FORCE)

class MFCcheckerUserCommandProcessor(UserCommandProcessor):

    def __init__(self,app):
        UserCommandProcessor.__init__(self)
        self.app = app 

    def _configureCommands(self):
        self.USER_COMMANDS_LABELS.STOP = "STOP"
        self.USER_COMMANDS_LABELS.WHO = "WHO"
        self.USER_COMMANDS_LABELS.ADD = "ADD"
        self.USER_COMMANDS_LABELS.REMOVE = "REMOVE"
        self.USER_COMMANDS_LABELS.NONOTIFY = "NONOTIFY"
        self.USER_COMMANDS_LABELS.NONOTIFY_INITIAL = "NONOTIFY_INITIAL"
        self.USER_COMMANDS_LABELS.NOTIFY = "NOTIFY"
        self.USER_COMMANDS_LABELS.NOTIFY_INITIAL = "NOTIFY_INITIAL"
        self.USER_COMMANDS_LABELS.LOGLEVEL = "LOGLEVEL"
        self.USER_COMMANDS_LABELS.INTERVAL = "INTERVAL"
        self.USER_COMMANDS_LABELS.SHOWCONFIG = "SHOWCONFIG"
        self.USER_COMMANDS_LABELS.MUTE = "MUTE"
        self.USER_COMMANDS_LABELS.UNMUTE = "UNMUTE"
        self.USER_COMMANDS_LABELS.TRANSITION = "TRANSITION"
        self._addCommands({
            self.USER_COMMANDS_LABELS.STOP: {
                "description": "Stop the program",
                "fct": "_execute_stop" },
            self.USER_COMMANDS_LABELS.WHO: {
                "description": "Show the list of online and offline models",
                "fct": "_execute_who" },
            self.USER_COMMANDS_LABELS.ADD: {
                "description": "Add a model to the list of models to check. Argument: model name",
                "fct": "_execute_add" },
            self.USER_COMMANDS_LABELS.REMOVE: {
                "description": "Remove a model from the list of models to check. Argument: model name",
                "fct": "_execute_remove" },
            self.USER_COMMANDS_LABELS.NONOTIFY: {
                "description": "Turn off desktop notifications. Re-activate them with the command "+self.USER_COMMANDS_LABELS.NOTIFY.lower(),
                "fct": "_execute_nonotify" },
            self.USER_COMMANDS_LABELS.NONOTIFY_INITIAL: {
                "description": "Turn off desktop notifications on the first check. Re-activate them with the command "+self.USER_COMMANDS_LABELS.NOTIFY_INITIAL.lower(),
                "fct": "_execute_nonotify_initial" },
            self.USER_COMMANDS_LABELS.NOTIFY: {
                "description": "Turn on desktop notifications. De-activate them with the command "+self.USER_COMMANDS_LABELS.NONOTIFY.lower(),
                "fct": "_execute_notify" },
            self.USER_COMMANDS_LABELS.NOTIFY_INITIAL: {
                "description": "Turn on desktop notifications on the first check. De-activate them with the command "+self.USER_COMMANDS_LABELS.NONOTIFY_INITIAL.lower(),
                "fct": "_execute_notify_initial" },
            self.USER_COMMANDS_LABELS.LOGLEVEL: {
                "description": "Temporarily change the amount of logging. Argument: logging level (TRACE, DEBUG, INFO, WARN, ERROR, FATAL)",
                "fct": "_execute_loglevel" },
            self.USER_COMMANDS_LABELS.LIST: {
                "description": "List the available user commands",
                "fct": "_execute_list" },
            self.USER_COMMANDS_LABELS.INTERVAL: {
                "description": "Adjust the checking interval. Don't put it lower than 20 seconds or the system will collapse. Argument: interval (in seconds)",
                "fct": "_execute_interval" },
            self.USER_COMMANDS_LABELS.SHOWCONFIG: {
                "description": "Show the application configuration",
                "fct": "_execute_showconfig" },
            self.USER_COMMANDS_LABELS.MUTE: {
                "description": "Temporarily stop checking for a model. Model remains muted until the program is restarted or unmuted manually",
                "fct": "_execute_mute" },
            self.USER_COMMANDS_LABELS.UNMUTE: {
                "description": "Start checking for a model that has been muted. Can also be used to temporarily start checking for a new model.",
                "fct": "_execute_unmute" },
            self.USER_COMMANDS_LABELS.TRANSITION: {
                "description": "Indicate which transitions in model state should be shown. Supported commands:\n                     * "+self.USER_COMMANDS_LABELS.TRANSITION.lower()+" offline true\n                     * "+self.USER_COMMANDS_LABELS.TRANSITION.lower()+" offline false",
                "fct": "_execute_transition" }
            })

    def _execute_stop(self):
        raise KeyboardInterrupt

    def _execute_who(self):
        self.app.displayStatus(log_level=Logger.LOG_LEVELS.FORCE)

    def _execute_add(self,model_names,persist=True):
        if not self._check_input_model_names(model_names):
            return

        for model_name in model_names:
            model = self.app.getModel(model_name)
            if model:
                LOGGER.printline("Model already in list of models that is checked",log_level=Logger.LOG_LEVELS.WARN)
                continue
    
            self.app.models.append(MFCModel(model_name))
            if persist:
                self.app.db_connector.add_model(model_name)
            LOGGER.printline("Model "+model_name+" added",log_level=Logger.LOG_LEVELS.FORCE)

        #threading.Timer(self.app.checking_interval+1, self.app.recheckConsistency).start()

    def _execute_remove(self,model_names,persist=True):
        if not self._check_input_model_names(model_names):
            return

        for model_name in model_names:
            model = self.app.getModel(model_name)
            if not model:
                LOGGER.printline("Model not yet in the list of models that is checked",log_level=Logger.LOG_LEVELS.WARN)
                continue

            self.app.models.remove(model)
            if persist:
                self.app.db_connector.remove_model(model_name)
            LOGGER.printline("Model "+model_name+" removed",log_level=Logger.LOG_LEVELS.FORCE)

    def _execute_unmute(self,model_names):
        if not self._check_input_model_names(model_names):
            return

        for model_name in model_names:
            model = self.app.getModel(model_name)
            if model:
                if model.isMuted:
                   model.isMuted = False
                   LOGGER.printline("Model unmuted.",log_level=Logger.LOG_LEVELS.FORCE)
                else:
                   LOGGER.printline("Model is already unmuted.",log_level=Logger.LOG_LEVELS.WARN)
            else:
                self._execute_add(model_names, persist=False)

    def _execute_mute(self,model_names):
        if not self._check_input_model_names(model_names):
            return

        for model_name in model_names:
            model = self.app.getModel(model_name)
            if model:
                if not model.isMuted:
                   model.isMuted = True
                   LOGGER.printline("Model muted.",log_level=Logger.LOG_LEVELS.FORCE)
                else:
                   LOGGER.printline("Model is already muted.",log_level=Logger.LOG_LEVELS.WARN)
            else:
                LOGGER.printline("Can not mute a model that is not yet in the list of checked models.",log_level=Logger.LOG_LEVELS.ERROR)

    def _execute_nonotify(self):
        LOGGER.desktop_notifications_activated=False
        self.app.db_connector.update_default_value("DESKTOP_NOTIFICATIONS_ACTIVATED","N")
        LOGGER.printline("Desktop notifications disabled",log_level=Logger.LOG_LEVELS.FORCE)

    def _execute_nonotify_initial(self):
        self.app.initial_dektop_notify_enabled=False
        self.app.db_connector.update_default_value("DESKTOP_NOTIFICATIONS_INITIAL","N")
        LOGGER.printline("Initial desktop notifications disabled",log_level=Logger.LOG_LEVELS.FORCE)

    def _execute_notify(self):
        LOGGER.desktop_notifications_activated=True
        self.app.db_connector.update_default_value("DESKTOP_NOTIFICATIONS_ACTIVATED","Y")
        LOGGER.printline("Desktop notifications enabled",log_level=Logger.LOG_LEVELS.FORCE)

    def _execute_notify_initial(self):
        self.app.initial_dektop_notify_enabled=True
        self.app.db_connector.update_default_value("DESKTOP_NOTIFICATIONS_INITIAL","Y")
        LOGGER.printline("Initial desktop notifications enabled",log_level=Logger.LOG_LEVELS.FORCE)

    def _execute_loglevel(self,arguments):
        if not arguments and not len(arguments) == 1:
            LOGGER.printline("Unknown log level "+arguments,log_level=Logger.LOG_LEVELS.ERROR)
            return

        try:
            given_level=arguments[0].upper()
            level=getattr(Logger.LOG_LEVELS,given_level)
            LOGGER.log_level=level
            LOGGER.printline("Log level set to "+given_level,log_level=Logger.LOG_LEVELS.FORCE)
        except AttributeError:
            LOGGER.printline("Unknown log level "+arguments[0],log_level=Logger.LOG_LEVELS.ERROR)
            return

    def _execute_interval(self,arguments):
        if not arguments and not len(arguments) == 1:
            LOGGER.printline("Unknown log level "+str(arguments),log_level=Logger.LOG_LEVELS.ERROR)
            return

        try:
            interval = float(arguments[0])
        except ValueError:
            LOGGER.printline("Given interval does not seem valid "+arguments[0],log_level=Logger.LOG_LEVELS.ERROR)
            return

        self.app.checking_interval=interval
        self.app.db_connector.update_default_value("CHECKING_INTERVAL",interval)
        LOGGER.printline("Interval set to "+str(interval),log_level=Logger.LOG_LEVELS.FORCE)
    
    def _execute_showconfig(self):
        log_level_label = Logger.log_level_label(LOGGER.log_level)
        if log_level_label != "":
            log_level_label += " ("+str(LOGGER.log_level)+")"
        else:
            log_level_label = str(LOGGER.log_level)

        LOGGER.printline("\n    All models to check:\n        "+"\n        ".join(map(str,self.app.models))
                        +"\n    Interval is set to "+str(self.app.checking_interval)
                        +"\n    Desktop notifications enabled: "+str(LOGGER.desktop_notifications_activated)
                        +"\n    Inital desktop notifications enabled: "+str(self.app.initial_dektop_notify_enabled)
                        +"\n    Log level is set to "+log_level_label
                        +"\n    Show transition to offline: "+str(self.app.display_transition_to_offline),log_level=Logger.LOG_LEVELS.FORCE)

    def _execute_transition(self,arguments):
        if not arguments and not len(arguments) == 2:
            LOGGER.printline("Invalid command structure",log_level=Logger.LOG_LEVELS.ERROR)
            return

        transition_type = arguments[0].lower()
        if transition_type == "offline":
            to_value = eval(arguments[1].title())
            if to_value == self.app.display_transition_to_offline:
                LOGGER.printline("Already configured like this. Configuration not updated.",log_level=Logger.LOG_LEVELS.FORCE)
                return
            self.app.display_transition_to_offline = to_value
            self.app.db_connector.update_default_value("SHOW_TRANSITION_TO_OFFLINE", "Y" if to_value else "N")
            LOGGER.printline("Now"+(" no longer" if not to_value else "")+" showing the transition to offline",log_level=Logger.LOG_LEVELS.FORCE)
        else:
            LOGGER.printline("Invalid command structure",log_level=Logger.LOG_LEVELS.ERROR)

    def _check_input_model_names(self, model_names):
        if not model_names or not len(model_names) > 0 or model_names[0].rstrip() == "":
            LOGGER.printline("Missing model name",log_level=Logger.LOG_LEVELS.ERROR)
            return False
        return True

class ApplicationDatabaseConnector:
    TABLE_DEFAULTS = "application_defaults"
    TABLE_MODELS = "models"

    def __init__(self, db_name, application_id = 0):
        self.application_id = application_id
        self.connection = sqlite3.connect(db_name) 

    def close(self):
        self.connection.close()

    def get_models(self):
        cursor = self.connection.cursor()
        models=[]
        for model in cursor.execute("select model_name from "+ApplicationDatabaseConnector.TABLE_MODELS+" where to_check='Y'"):
            models.append(model[0])
        return models

    def add_model(self,model_name):
        try:
            cursor = self.connection.cursor()
            cursor.execute("select to_check from "+ApplicationDatabaseConnector.TABLE_MODELS+" where model_name=?",(model_name,))
            row = cursor.fetchone()
            if row is None:
                cursor.execute("insert into "+ApplicationDatabaseConnector.TABLE_MODELS+" (model_name,to_check) values (?,'Y')",(model_name,))
            else:
                to_check = row[0]
                if to_check == "N":
                    cursor.execute("update "+ApplicationDatabaseConnector.TABLE_MODELS+" set to_check='Y' where model_name=?",(model_name,))
            self.connection.commit()
        except Exception as exc:
           self.connection.rollback()
           raise exc

    def remove_model(self,model_name):
        try:
            cursor = self.connection.cursor()
            cursor.execute("select to_check from "+ApplicationDatabaseConnector.TABLE_MODELS+" where model_name=? and to_check='Y'",(model_name,))
            row = cursor.fetchone()
            if row is not None:
                cursor.execute("update "+ApplicationDatabaseConnector.TABLE_MODELS+" set to_check='N' where model_name=?",(model_name,))
            self.connection.commit()
        except Exception as exc:
           self.connection.rollback()
           raise exc

    def retrieve_default_value(self,name):
        cursor = self.connection.cursor()
        cursor.execute("select value,conversion_function from "+ApplicationDatabaseConnector.TABLE_DEFAULTS+" where application_id=? and name=?",(self.application_id,name))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Default value not found.")
        value=row[0]
        conversion_function=row[1]
        if conversion_function == "":
            return value
        else:
            try:
                fct = getattr(self,"_convert_"+conversion_function)
            except Exception:
                LOGGER.printline("Unknown conversion function when retrieving default value of"+name,log_level=Logger.LOG_LEVELS.WARN)
                return value

            return fct(value)

    def _convert_str_to_double(self,string):
        return float(string)
    def _convert_str_to_boolean(self,string):
        if string == "Y":
            return True
        return False

    def update_default_value(self,name,value):
        try:
            cursor = self.connection.cursor()
            cursor.execute("update "+ApplicationDatabaseConnector.TABLE_DEFAULTS+" set value=? where application_id=? and name=?",(str(value),self.application_id,name))
            self.connection.commit()
        except Exception as exc:
            self.connection.rollback()
            raise exc

if __name__ == '__main__':

    try:
        db_connector = ApplicationDatabaseConnector(APPLICATION_DATABASE)
        desktop_notifications=db_connector.retrieve_default_value("DESKTOP_NOTIFICATIONS_ACTIVATED")
    finally:
        if db_connector:
            db_connector.close()
    if desktop_notifications is not None:
        LOGGER = Logger(desktop_notifications_activated=desktop_notifications)
    else:
        LOGGER = Logger()

    mainApp = MainApplication()
    userCommandProcessor = MFCcheckerUserCommandProcessor(mainApp)

    try:
        mainApp.start()

        time.sleep(2)
        LOGGER.printline("Initializing command line...",log_level=Logger.LOG_LEVELS.INFO)
        time.sleep(2)
        LOGGER.printline("Use command 'list' to get an overview of application commands",log_level=Logger.LOG_LEVELS.INFO)

        while mainApp.isAlive():
            try:
                LOGGER.show_user_input_prompt=True
                cmd = raw_input(">> ")
                LOGGER.show_user_input_prompt=False
                userCommandProcessor.execute(cmd)
            except Exception as exc:
                LOGGER.show_user_input_prompt=False
                LOGGER.printline('Error: '+str(exc),log_level=Logger.LOG_LEVELS.ERROR)
                pass
            mainApp.join(1)
    except KeyboardInterrupt:
        LOGGER.printline("Exiting...",log_level=Logger.LOG_LEVELS.INFO)
        mainApp.stopApplication()
        exit(0)

