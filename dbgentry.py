try:
    import logging
    import blessed

    import voltron
    from voltron.core import Server
    from voltron.plugin import PluginManager
    try:
        import lldb
        in_lldb = True
    except ImportError:
        in_lldb = False
    try:
        import gdb
        in_gdb = True
    except ImportError:
        in_gdb = False

    voltron.setup_env()
    log = voltron.setup_logging('debugger')

    class VoltronCommand (object):
        """
        Parent class for common methods across all debugger hosts.
        """
        def handle_command(self, command):
            global log
            if "status" in command:
                self.status()
            elif 'debug' in command:
                if 'enable' in command:
                    log.setLevel(logging.DEBUG)
                    print("Debug logging enabled")
                elif 'disable' in command:
                    log.setLevel(logging.INFO)
                    print("Debug logging disabled")
                else:
                    enabled = "enabled" if log.getEffectiveLevel() == logging.DEBUG else "disabled"
                    print("Debug logging is currently " + enabled)
            elif 'init' in command:
                self.register_hooks()
            elif 'stopped' in command:
                self.adaptor.update_state()
            else:
                print("Usage: voltron <status|debug>")

        def status(self):
            if self.server != None:
                summs = self.server.client_summary()
                print("The following listeners are active:")
                listen = voltron.config['server']['listen']
                if listen['domain']:
                    print("  domain socket ({})".format(voltron.env['sock']))
                if listen['tcp']:
                    print("  TCP socket ({})".format(listen['tcp']))
                if listen['http']:
                    print("  web server ({})".format(listen['http']))
                print("There are {} clients attached:".format(len(summs)))
                for summary in summs:
                    print("  " + summary)
            else:
                print("Server is not running (no inferior)")


    if in_lldb:
        class VoltronLLDBCommand (VoltronCommand):
            """
            Debugger command class for LLDB
            """
            def __init__(self, debugger, dict):
                super(VoltronCommand, self).__init__()

                # grab the debugger and command interpreter
                self.debugger = debugger
                self.ci = self.debugger.GetCommandInterpreter()

                # install the voltron command handler
                self.debugger.HandleCommand('command script add -f dbgentry.lldb_invoke voltron')

                # load plugins
                self.pm = PluginManager()

                # set up an lldb adaptor and set it as the package-wide adaptor
                self.adaptor = self.pm.debugger_plugin_for_host('lldb').adaptor_class()
                voltron.debugger = self.adaptor

                # start the server
                self.server = Server()
                self.server.start()

                self.hook_idx = None

            def invoke(self, debugger, command, result, dict):
                self.handle_command(command)

            def register_hooks(self):
                try:
                    output = self.adaptor.command("target stop-hook list")
                    if not 'voltron' in output:
                        output = self.adaptor.command('target stop-hook add -o \'voltron stopped\'')
                        try:
                            # hahaha this sucks
                            self.hook_idx = int(res.GetOutput().strip().split()[2][1:])
                        except:
                            pass
                    print("Registered stop-hook")
                except:
                    print("No targets")

            def unregister_hooks(self):
                cmd = 'target stop-hook delete {}'.format(self.hook_idx if self.hook_idx else '')
                self.debugger.HandleCommand(cmd)

        def __lldb_init_module(debugger, env_dict):
            """
            Called by LLDB when the module is loaded
            """
            if not 'cmd' in env_dict:
                log.debug("Initialising LLDB command")
                env_dict['cmd'] = VoltronLLDBCommand(debugger, env_dict)
                print(blessed.Terminal().bold_red("Voltron loaded."))
                print("Run `voltron init` after you load a target.")

        def lldb_invoke(debugger, command, result, env_dict):
            """
            Called when the voltron command is invoked within LLDB
            """
            env_dict['cmd'].invoke(debugger, command, result, env_dict)


    if in_gdb:
        class VoltronGDBCommand (VoltronCommand, gdb.Command):
            """
            Debugger command class for GDB
            """
            def __init__(self):
                super(VoltronCommand, self).__init__("voltron", gdb.COMMAND_NONE, gdb.COMPLETE_NONE)

                # load plugins
                self.pm = PluginManager()

                # set up a gdb adaptor and set it as the package-wide adaptor
                self.adaptor = self.pm.debugger_plugin_for_host('gdb').adaptor_class()
                voltron.debugger = self.adaptor

                # server is started and stopped with the inferior to avoid GDB hanging on exit
                self.server = None

            def invoke(self, arg, from_tty):
                self.handle_command(arg)

            def register_hooks(self):
                gdb.events.stop.connect(self.stop_handler)
                gdb.events.exited.connect(self.exit_handler)
                gdb.events.cont.connect(self.cont_handler)

            def unregister_hooks(self):
                gdb.events.stop.disconnect(self.stop_handler)
                gdb.events.exited.disconnect(self.exit_handler)
                gdb.events.cont.disconnect(self.cont_handler)

            def stop_handler(self, event):
                self.adaptor.update_state()
                log.debug('Inferior stopped')

            def exit_handler(self, event):
                log.debug('Inferior exited')
                self.server.stop()

            def cont_handler(self, event):
                log.debug('Inferior continued')
                if self.server == None:
                    self.server = Server()
                    self.server.start()


        if __name__ == "__main__":
            log.debug('Initialising GDB command')
            inst = VoltronGDBCommand()
            print(blessed.Terminal().bold_red("Voltron loaded."))


except Exception, e:
    print(blessed.Terminal().bold_red("Exception {} raised while loading Voltron: {}".format(type(e), str(e))))
