"""
DRBot - a geodatabase bot using Data Reviewer

This script executes a list of .rbj files, writes the result into a DR enabled gdb, and sends an email summarising
the findings. It works with both ArcMap and ArcGIS Pro.

The code is not a clean and streamlined as it could be, but it works ok for our purposes and can hopefully still be 
helpful and/or inspirational. 

Hard-coded settings are located near the beginning and the end of this file.

COMMAND LINE SYNTAX:
drbot.py [rulefile [logfile [database [email]]]]
e.g. drbot.py rules\weekly.txt logs\nulls.log editor@ora.sde user@email.org

rulefile may be a single .rbj file, or a txt file containing a list of rbj files, one per line

logfile is the location of the output log

database is the database to be checked (fgdb or sde)

email may be a comma-separated list

In this mode, the DR output is written to a pre-defined location (can easily be changed).

The tool can also be invoked as "drbot.py clean", which will simply clear the DR workspace and do nothing else. This 
can be useful e.g. when running a weekly batch, and you want to regularly clear out old outputs.

If you want to use a template gdb for creating your DR gdb, it should contain a session called 'empty'
('Session 1 : empty'). This session will then be used as template session for created DR sessions. For example, we
used to have a template that disabled the default check for invalid geometries (but that seems to be the default
behaviour since ~10.4).

TODO:
- include information in the email about which rbj files triggered each findings
- clean up error handling in clean_dr_ws(), make_dr_gdb(), prep_dr_ws() (and everywhere else...)
- use logging_with_arcpy instead of TmpLog

Author: Hanne L. Petersen <halpe@sdfe.dk>
Download: https://github.com/Kortforsyningen/drbot
"""
import os
import sys
import shutil
from datetime import datetime as dt
import traceback

import arcpy

found_marker = "Found"  # indicator of errors in log file/mail, and used for counting for the summary

# Organisation's email settings
email_server = "smtp.organisation.net"
email_sender = "Batch Script <batch_user@organisation.net>"


class DRBot:
    """A class to run Data Reviewer's rbj-files and report output."""

    def __init__(self, db, dr_gdb_location, template_dr_gdb='', coord_sys=arcpy.SpatialReference(4326)):
        """
        Initialise the DRBot object.
        
        db: The data to be checked.
        dr_gdb_location: The DR gdb/workspace where errors will be written. May or may not exist already.
        template_dr_gdb: A template for creating the dr_gdb, if it doesn't already exist. 
        coord_sys: The default coordinate system used if the DR workspace needs to be DR enabled.
        """
        self.db = db
        self.dr_gdb_location = dr_gdb_location
        self.template_dr_gdb = template_dr_gdb
        self.coord_sys = coord_sys
        self.tmp_log = TmpLog()  # Initialise log

    def run_from_sysargs(self, def_rules):
        """Run a DRBot check from command line inputs."""
        rules = def_rules
        logfile = ""
        mails = ""

        if len(sys.argv) == 2 and sys.argv[1] == 'clean':
            self.clean_dr_ws()
            self.tmp_log.log("Cleanup completed.")
            return

        if len(sys.argv) > 1:
            rules = sys.argv[1]

        if len(sys.argv) > 2:
            logfile = sys.argv[2]

        if len(sys.argv) > 3:
            self.db = sys.argv[3]

        if len(sys.argv) > 4:
            mails = sys.argv[4].split(',')

        sess_name = logfile[1 + logfile.rfind('\\'):]
        self.runDR(rules, sess_name)

        self.report_output(logfile, mails, rules.split('\\')[-1])

    def report_output(self, logfile, mails, subj, always_send_mail=True):
        """Report output (from tmp_log) to desired channels."""
        if mails == [""]:
            mails = ""

        # Write output to log file
        if len(logfile) > 0:
            self.tmp_log.write_to_file(logfile)

        # Check if errors have been found and there's someone to email
        if not always_send_mail and len(mails) > 0:
            if self.tmp_log.contains_line_with(found_marker):
                always_send_mail = True

        # Send log contents to email
        if always_send_mail and len(mails) > 0:
            self.tmp_log.send_email(email_sender, mails, 'DRBot Run, {}'.format(subj), found_marker)

    @staticmethod
    def fix_path(path, basepath):
        """If path is relative, make it absolute by prefixing basepath."""
        if path[1] != ":" and path[0] != "/":
            return os.path.join(basepath, path)
        return path

    def runDR(self, rules, sess_keywd):
        """Run Data Reviewer with the specified rules. Report output to DR gdb and tmp_log."""
        self.tmp_log.log("Start time: " + str(dt.now()))

        # Check out a Data Reviewer extension license
        arcpy.CheckOutExtension("datareviewer")

        session_name = sess_keywd  # + " - " + time.strftime('%H') + "h, scheduled DR session"

        set_msg("Loading rule file(s) from {}...".format(rules))
        if '.txt' in rules:  # if it's a txt file, read it as lines of rbj files
            try:
                with open(rules, 'r') as indata:
                    # Get file contents, skip lines starting with #
                    rulefiles = [DRBot.fix_path(lin, os.path.dirname(rules))
                                 for lin in indata.read().splitlines() if lin[:1] != "#"]
            except IOError as exc:
                set_msg("ERROR reading rules {}.".format(rules))
                if exc[0] == 2:
                    set_msg(exc[1])  # no such file or dir
                    return 1
                else:
                    set_msg(traceback.format_exc())
        else:
            rulefiles = [rules]

        t0 = dt.now()

        try:
            # Ensure that we have a Data Reviewer Session (create gdb etc. if necessary)
            self.prep_dr_ws(session_name)

            # Find session in table, and get its session id
            sessionnamefld = arcpy.AddFieldDelimiters(self.dr_gdb_location + "\\GDB_REVSESSIONTABLE", "SESSIONNAME")
            session_where = "%s = '%s'" % (sessionnamefld, session_name)
            cur = arcpy.SearchCursor(self.dr_gdb_location + "\\GDB_REVSESSIONTABLE", session_where)
            for row in cur:
                sess_obj_id = row.getValue("SESSIONID")

            # This is the string value needed to WRITE to the newly created session
            # Note: This *must* have this format, with space before the colon, or the script will fail!
            sessionidstr = "Session %d : %s" % (sess_obj_id, session_name)
            set_msg("  Created session:\n    %s" % sessionidstr)
            self.tmp_log.log("Checking {}".format(self.db))
            self.tmp_log.log("Errors will be written to {}".format(self.dr_gdb_location))

            # Check using each rule file
            for rulefile in rulefiles:
                set_msg('  Checking file: '+rulefile)
                try:
                    print("Rules: "+rulefile)
                    arcpy.ExecuteReviewerBatchJob_Reviewer(self.dr_gdb_location, sessionidstr, rulefile, self.db)
                except arcpy.ExecuteError as ee:
                    # print(arcpy.GetMessages())
                    err = parse_arc_error(ee)
                    if err == 732:
                        self.tmp_log.log("Found execution error: File {} not found.".format(rulefile))
                        # print(repr(ee))
                    else:
                        raise ee

            set_msg("Checks completed, summarising output.\n\n")
            self.summarise_dr_output(sess_obj_id)

        except Exception as exc:
            set_msg("Exception during DRBot " + str(exc))
            set_msg(traceback.format_exc())

        # Check in the Data Reviewer extension
        arcpy.CheckInExtension("datareviewer")

        self.tmp_log.log("Done")

        dur_run = dt.now() - t0
        self.tmp_log.log("\nTotal " + __file__ + " duration (h:mm:ss.dd): " + str(dur_run)[:-3])

    def clean_dr_ws(self):
        """Clean out any existing DR workspace gdb (delete and create)."""
        set_msg("Cleaning up DR gdb...")
        if os.path.isdir(self.dr_gdb_location):
            try:
                set_msg("Deleting DR gdb " + self.dr_gdb_location + "...")
                shutil.rmtree(self.dr_gdb_location)
            except Exception as exc:
                set_msg("Failed to delete existing DR gdb.")
                if exc[0] == 32:
                    set_msg("  " + exc[1])  # file is in use
                    return 1
                else:
                    set_msg("Exception during DR workspace cleanup " + str(exc))
                    set_msg(traceback.format_exc())
            self.make_dr_gdb()

    def make_dr_gdb(self):
        """Create a gdb for use by DR. Use template if available."""
        set_msg("Making DR gdb...")
        if os.path.isdir(self.template_dr_gdb):  # Create using template
            try:
                shutil.copytree(self.template_dr_gdb, self.dr_gdb_location)
            except shutil.Error as exc:
                set_msg("  Couldn't copy DR gdb template (shutil.Error).")
                set_msg("  errors: " + str(exc.args[0]))
            except Exception as exc:
                set_msg("  Couldn't copy DR gdb template (non-shutil.Error).")
                if exc[0] == 183:
                    set_msg("  " + exc[1])  # cannot create a file that already exists
                else:
                    set_msg("  Exception while copying template gdb: " + str(exc))
                    # set_msg(repr(exc))
                    # set_msg(traceback.format_exc())
                pass
        # if DRgdb[:-1] in ('/', '\\'):  # don't allow trailing slash (os.path.dirname will fail)
        #     DRgdb = DRgdb[0:-1]
        if not os.path.isdir(self.dr_gdb_location):
            set_msg("Creating empty fgdb for DR...")
            try:
                arcpy.CreateFileGDB_management(os.path.dirname(self.dr_gdb_location),
                                               os.path.basename(self.dr_gdb_location))
                # if it's already enabled, this apparently just does nothing
                arcpy.EnableDataReviewer_Reviewer(self.dr_gdb_location, self.coord_sys)
            except Exception as esc:
                set_msg("Couldn't create empty gdb for DR workspace.")
                return 1

    def prep_dr_ws(self, session_name):
        """
        Ensure that we have a valid Data Reviewer Session (create gdb etc. if necessary).
        
        Use 'Session 1 : empty' as session template if available.
        """
        set_msg("Preparing Data Reviewer Session...")

        if not os.path.isdir(self.dr_gdb_location):
            self.make_dr_gdb()

        # Create session
        set_msg("    Database: " + self.dr_gdb_location)
        try:
            arcpy.CreateReviewerSession_Reviewer(self.dr_gdb_location, session_name, 'Session 1 : empty')
        except arcpy.ExecuteError as exc:  # an ExecuteError is thrown if 'Session 1 : empty' doesn't exist
            set_msg("  Couldn't create reviewer session from template, ignoring template.")
            # if exc[0] == 837:
            #     set_msg("  " + exc[1])  # workspace is not the correct workspace type
            try:
                # self.tmp_log.log("Warning found: couldn't use workspace template.")
                arcpy.CreateReviewerSession_Reviewer(self.dr_gdb_location, session_name)
            except Exception as exc2:
                set_msg("Problem while creating empty reviewer session: ")
                set_msg(traceback.format_exc())

    def summarise_dr_output(self, sess_obj_id):
        """Read the REVTABLEMAIN table from the DR gdb to examine the findings, summarise into tmp_log."""
        fields = ["CHECKTITLE", "ORIGINTABLE", "SUBTYPE", "OBJECTID", "NOTES"]
        check_count = 0
        prev_check = ''
        for row in arcpy.da.SearchCursor(self.dr_gdb_location + '/REVTABLEMAIN', fields,
                                         where_clause='SESSIONID=' + str(sess_obj_id),
                                         sql_clause=('', 'ORDER BY CHECKTITLE, OBJECTID')):
            (title, fc, fcs, objectid, notes) = row
            if title != prev_check:
                if prev_check != '':
                    self.tmp_log.log("Total {} DRBot hits for {}\n".format(check_count, prev_check))
                prev_check = title
                check_count = 0
            check_count += 1
            fcs_str = ", " + fcs[:6] if len(fcs) > 0 else ""
            self.tmp_log.log(found_marker + " {}{}, OBJECTID={}: {} ({})"
                             .format(fc, fcs_str, objectid, encode_if_unicode(title), encode_if_unicode(notes)))
        if prev_check != '':
            self.tmp_log.log("Total {} DRBot hits for {}\n".format(check_count, prev_check))

        # TODO: look in REVCHECKRUNTABLE for the rbj filename and print it here; using the column CHECKRUNID

        if self.tmp_log.count_lines_with(found_marker) == 0:
            self.tmp_log.log("No errors found.")

# end class DRBot


def set_msg(s):
    arcpy.AddMessage(s)


def encode_if_unicode(strval):
    """Encode if string is unicode."""
    try:
        if isinstance(strval, unicode):
            return strval.encode('utf8')
    except:
        pass
    return str(strval)


def parse_arc_error(e):
    import re
    obj = re.search('ERROR 0+([1-9]\d*):', e.message)
    if obj is None:
        raise e
    return int(obj.group(1))


class TmpLog:
    """
    A class to store and use temporary logs, i.e. until end of script execution.

    Current main usage is for compiling logs that will send off by email after completion.

    Temporary logs can be accessed during execution, but will not survive end-of-execution
    (unless handed over to somewhere else before that).
    """

    def __init__(self):
        self.tmp_log_list = []  # Collector for logged items
        pass

    def log(self, msg):
        """Log msg. At most until end of execution."""
        self.tmp_log_list.append(str(msg))

    def count_lines_with(self, s):
        """Count the number of lines in log containing s."""
        cnt = 0
        for itm in self.tmp_log_list:
            if s in itm:
                cnt += 1
        return cnt

    def contains_line_with(self, s):
        """Check if any line in log contains s."""
        for itm in self.tmp_log_list:
            if s in itm:
                return True
        return False

    def write_to_file(self, filename):
        """Write contents of log to file."""
        with open(filename, 'w') as the_file:
            for logline in self.tmp_log_list:
                the_file.write("%s\n" % logline)

    def send_email(self, sender, email_lst, subject, count_flag):
        """Email the contents of the log to email_lst, reporting occurrences of countFlag in email subject."""
        import smtplib
        message = ''
        issue_count = 0
        for logline in self.tmp_log_list:
            message += "{}\n".format(logline)
            if count_flag in str(logline):
                issue_count += 1
        if count_flag != '':
            subject = "{} - {} issues".format(subject, issue_count)
        body = """From: %s\nTo: %s\nSubject: %s\n\n%s
        """ % (sender, ", ".join(email_lst), subject, message)

        # Send the email
        try:
            server = smtplib.SMTP(email_server)
            server.sendmail(sender, email_lst, body)
            server.quit()
        except Exception as e:
            print("Couldn't send email.")
            print(repr(e))
        pass


if __name__ == "__main__":

    # Test inputs
    coord_sys = arcpy.SpatialReference(4326)
    dr_ws_loc = r"c:\temp\drbot_test.gdb"
    log_loc = "log.txt"
    dr_ws_tpl = ''  # r"C:\arcgis\test\DataReviewer\sample_DR_tpl.gdb"
    data = r'C:\arcgis\test\DataReviewer\testdata.gdb'
    rule_loc = r'rules\sample1.rbj'
    sendmails = []

    test_drb = DRBot(data, dr_ws_loc, dr_ws_tpl, coord_sys)
    if len(sys.argv) > 1:
        test_drb.run_from_sysargs(rule_loc)
    else:
        sess_name = log_loc[1 + log_loc.rfind('\\'):]
        test_drb.runDR(rule_loc, sess_name)
        test_drb.report_output(log_loc, sendmails, 'DRBot run, {}'.format(rule_loc.split('\\')[-1]), False)
