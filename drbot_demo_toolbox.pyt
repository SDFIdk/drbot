import os
import arcpy

from drbot import DRBot


class Toolbox(object):
    """The main toolbox class."""
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the .pyt file)."""
        self.label = "DRBot Demo Toolbox"
        self.alias = ""

        # List of tool classes associated with this toolbox
        self.tools = [DRBotTool]


class DRBotTool(object):
    """Tool to perform operation."""

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "DRBot Tool"
        self.description = "DRBot is a tool for running Data Reviewer (DR)."
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions."""

        # Input parameters
        data_param = arcpy.Parameter(
            displayName="Data",
            name="data",
            datatype="Workspace",
            parameterType="Required",
            direction="Input")
        data_param.value = "Database Connections/data.sde"  # Default value
        # https://pro.arcgis.com/en/pro-app/arcpy/geoprocessing_and_python/defining-parameters-in-a-python-toolbox.htm

        rule_param = arcpy.Parameter(
            displayName="Rule File(s)",
            name="rules",
            datatype="String",
            parameterType="Required",
            direction="Input")
        rule_param.filter.type = "ValueList"
        rule_param.filter.list = ["rules/sample1.rbj", "rules/sample2.rbj"]
        rule_param.value = "rules/sample1.rbj"

        dr_ws_param = arcpy.Parameter(
            displayName="DR Workspace Location",
            name="dr_ws",
            datatype="String",
            parameterType="Required",
            direction="Input")
        dr_ws_param.value = r"c:\Temp\drbot_DR.gdb"

        sess_param = arcpy.Parameter(
            displayName="Session Name",
            name="sess_nam",
            datatype="String",
            parameterType="Required",
            direction="Input")
        sess_param.value = "DRBot Session"

        params = [data_param, rule_param, dr_ws_param, sess_param]
        return params

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""
        return

    def execute(self, parameters, messages):
        """Call the tool for execution."""
        data = parameters[0].valueAsText
        rule_loc = parameters[1].valueAsText
        dr_ws_loc = parameters[2].valueAsText
        sess_name = parameters[3].valueAsText
        log_loc = os.path.join(os.path.dirname(os.path.realpath(__file__)), "log.txt")
        sendmails = ''  # parameters[4].valueAsText.split(',')
        dr_ws_tpl = ''  # r"c:\temp\dr_tpl.gdb"
        coord_sys = arcpy.SpatialReference(4326)

        drb = DRBot(data, dr_ws_loc, dr_ws_tpl, coord_sys)
        drb.runDR(rule_loc, sess_name)
        drb.report_output(log_loc, sendmails, 'DRBot run, {}'.format(rule_loc.split('\\')[-1]), False)
        return
