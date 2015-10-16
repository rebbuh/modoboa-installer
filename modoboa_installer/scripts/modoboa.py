"""Modoboa related tasks."""

import os
import pwd
import stat

from .. import python
from .. import utils

from . import base
from . import install


class Modoboa(base.Installer):

    """Modoboa installation."""

    appname = "modoboa"
    no_daemon = True
    packages = [
        "python-dev", "libxml2-dev", "libxslt-dev", "libjpeg-dev",
        "librrd-dev", "rrdtool"]
    config_files = [
        "crontab=/etc/cron.d/modoboa",
        "sudoers=/etc/sudoers.d/modoboa",
    ]
    with_db = True
    with_user = True

    def __init__(self, config):
        """Get configuration."""
        super(Modoboa, self).__init__(config)
        self.venv_path = config.get("modoboa", "venv_path")
        self.instance_path = config.get("modoboa", "instance_path")
        self.extensions = config.get("modoboa", "extensions").split()

    def _setup_venv(self):
        """Prepare a dedicated virtuelenv."""
        python.setup_virtualenv(self.venv_path, sudo_user=self.user)
        packages = ["modoboa", "rrdtool"]
        if self.dbengine == "postgres":
            packages.append("psycopg2")
        else:
            packages.append("MYSQL-Python")
        python.install_packages(packages, self.venv_path, sudo_user=self.user)

    def _deploy_instance(self):
        """Deploy Modoboa."""
        prefix = ". {}; ".format(
            os.path.join(self.venv_path, "bin", "activate"))
        args = [
            "--collectstatic",
            "--timezone", self.config.get("modoboa", "timezone"),
            "--domain", self.config.get("general", "hostname"),
            "--extensions", " ".join(self.extensions),
            "--dburl", "default:{0}://{1}:{2}@localhost/{1}".format(
                self.config.get("database", "engine"), self.dbname,
                self.dbpasswd)
        ]
        if self.config.getboolean("amavis", "enabled"):
            args += [
                "amavis:{}://{}:{}@localhost/{}".format(
                    self.config.get("database", "engine"),
                    self.config.get("amavis", "dbuser"),
                    self.config.get("amavis", "dbpassword"),
                    self.config.get("amavis", "dbname")
                )
            ]

        utils.exec_cmd(
            "bash -c '{} modoboa-admin.py deploy instance {}'".format(
                prefix, " ".join(args)),
            sudo_user=self.user, cwd=self.home_dir)

    def get_template_context(self):
        """Additional variables."""
        context = super(Modoboa, self).get_template_context()
        context.update({
            "dovecot_mailboxes_owner": (
                self.config.get("dovecot", "mailboxes_owner"))
        })
        return context

    def apply_settings(self):
        """Configure modoboa."""
        rrd_root_dir = os.path.join(self.home_dir, "rrdfiles")
        pdf_storage_dir = os.path.join(self.home_dir, "pdfcredentials")
        webmail_media_dir = os.path.join(
            self.instance_path, "media", "webmail")
        pw = pwd.getpwnam(self.user)
        for d in [rrd_root_dir, pdf_storage_dir, webmail_media_dir]:
            utils.mkdir(d, stat.S_IRWXU | stat.S_IRWXG, pw[2], pw[3])
        settings = {
            "modoboa_admin.HANDLE_MAILBOXES": "yes",
            "modoboa_admin.AUTO_ACCOUNT_REMOVAL": "yes",
            "modoboa_amavis.AM_PDP_MODE": "inet",
            "modoboa_stats.RRD_ROOT_DIR": rrd_root_dir,
            "modoboa_pdfcredentials.STORAGE_DIR": pdf_storage_dir,
        }

        for name, value in settings.items():
            query = (
                "DELETE FROM lib_parameter WHERE name='{0}';"
                "INSERT INTO lib_parameter (name, value) VALUES ('{0}', '{1}')"
                .format(name, value)
            )
            self.backend._exec_query(query, self.dbname, self.dbuser)

    def post_run(self):
        """Additional tasks."""
        self._setup_venv()
        self._deploy_instance()
        self.apply_settings()
        install("uwsgi", self.config)
        install("nginx", self.config)
