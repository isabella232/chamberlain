import json
import os
import sys
import time
from abc import ABCMeta

import chamberlain.application as chap  # lols
import chamberlain.jenkins.configuration as jenkins_cfg
import chamberlain.git as git
from chamberlain.cli.command import Base
from chamberlain.config import Config
from chamberlain.jenkins import template as jenkins_template
from chamberlain.repo import repo_hash


def create_jobs(instance, workspace, cfg_overrides, template_dir=None):
    if template_dir is None:
        template_dir = workspace.template_subdir()
    instance_cfg = jenkins_cfg.InstanceConfig()
    instance_cfg.override_defaults(cfg_overrides)
    instance_path = os.path.join(workspace._wdir, instance)
    tmpl_path = "%s:%s" % (template_dir, instance_path)
    builder_opts = jenkins_cfg.BuilderOptions(tmpl_path)
    jenkins_cfg.ConfigurationRunner().run(builder_opts,
                                          instance_cfg)


def params_from_str(params):
    return {
        pieces[0]: pieces[1]
        for pieces in [p.split(":", 1) for p in params]
    }


class TemplatesCommand(Base):
    __metaclass__ = ABCMeta

    def __init__(self, log, config_file=None):
        super(TemplatesCommand, self).__init__(log, config_file)
        self.repos = None

    def configure_parser(self, parser):
        parser.add_argument("--api-url",
                            dest="api_url",
                            default=None,
                            help="Github API URL to use.")
        parser.add_argument("-f",
                            "--force-sync",
                            dest="force",
                            action="store_true",
                            default=False,
                            help="Force repository sync, ignoring cache.")
        parser.add_argument("-w",
                            "--workspace",
                            dest="workspace",
                            type=str,
                            default=os.path.join(chap.app_home(), "workspace"),
                            help="prepare a target template directory")

    def fetch_repos(self, orgs=[], filters=[], files=[], force=False,
                    api_url=None):
        if self.repos is None or force:
            gh_client = self.app.github(api_url)
            self.repos = gh_client.repo_list(force=force,
                                             filters=filters,
                                             file_filters=files,
                                             orgs=orgs)
        return self.repos


class OrgTemplatesCommand(TemplatesCommand):
    __metaclass__ = ABCMeta

    def __init__(self, log, config_file=None):
        super(OrgTemplatesCommand, self).__init__(log, config_file)
        self.mapping = None

    def configure_parser(self, parser):
        parser.add_argument("repos",
                            nargs="*",
                            default=[],
                            help="List of repositories to filter for.")
        parser.add_argument("--file-filter",
                            nargs="*",
                            default=[],
                            help="Only act on repo if it contains a file, or "
                                 "all given files")
        parser.add_argument("-t",
                            "--templates",
                            dest="templates",
                            nargs="*",
                            default=[os.getcwd()],
                            help="list of directories containing templates\
                                  (default: [ cwd() ]")
        super(OrgTemplatesCommand, self).configure_parser(parser)

    def repo_job_mapping(self, repos, file_filter, force=False, api_url=None):
        if self.mapping is None or force:
            repos = self.fetch_repos(filters=repos,
                                     files=file_filter,
                                     force=force,
                                     api_url=api_url)
            self.mapping = self.app.repo_mapper().map_configs(repos)
        return self.mapping


class GenerateTemplatesCommand(OrgTemplatesCommand):
    def configure_parser(self, parser):
        parser.add_argument("-p",
                            "--params",
                            nargs="*",
                            default=[],
                            help="List of params to inject (key:value)")
        super(GenerateTemplatesCommand, self).configure_parser(parser)

    def description(self):
        return "Generate templates & project groups from template files."

    def clean_workspace(self, workspace):
        self.log.title("Generating templates in %s" % workspace)
        self.app.workspace.set_dir(workspace)
        self.log.info("Cleaning %s ..." % self.app.workspace._wdir)
        self.app.workspace.clean()

    def repo_params(self, instance, repo_name, repo_data=None):
        instance_defaults = {}
        try:
            cfg = self.app.config.jenkins.template_params()
            instance_defaults = cfg[instance]
        except:
            pass
        if repo_data is None:
            repo_data = self.app.github().repo_data(repo_name)
        ret = {
            "name": "%s-%s" % (instance, repo_name),
            "repo": repo_data.name(),
            "owner": repo_data.owner(),
            "repo_full_name": repo_data.full_name(),
            "sshurl": repo_data.ssh_url(),
            "ghurl": repo_data.html_url()
        }
        ret.update(instance_defaults)
        return ret

    def copy_templates(self, templates=[]):
        self.log.info("Copying into workspace")
        self.app.workspace.copy_libs()
        for template_dir in templates:
            self.log.info("\t- %s" % template_dir)
            self.app.workspace.copy_templates(template_dir)

    def write_instance_templates(self, instance, repo, params, templates,
                                 template_params=[]):
        # first format the template params, it's a str array from CLI
        final_template_params = {}
        for template_params in template_params:
            (template_name, param_json) = template_params.split(":", 1)
            try:
                template_vars = json.loads(param_json)
                final_template_params[template_name] = template_vars
            except ValueError:
                self.log.warn("Template %s: invalid var JSON, skipping"
                              % template_name)

        # compile full template list with vars, if any
        final_jobs = []
        for template in templates:
            try:
                template_params = final_template_params[template]
                self.log.info("- %s - vars found:" % template)
                perms = []
                for (var, vals) in template_params.iteritems():
                    if len(perms) == 0:
                        perms = [{var: v} for v in set(vals)]
                        continue
                    temp = []
                    for val in set(vals):
                        for perm in perms:
                            new_perm = perm.copy()
                            new_perm[var] = val
                            temp.append(new_perm)
                    perms = temp
                for perm in perms:
                    self.log.info("\t- %s" % perm)
                    final_jobs.append({template: perm})
            except KeyError:
                self.log.info("- %s - no vars detected" % template)
                final_jobs.append(template)
            except Exception as err:
                self.log.error("Could not consolidate job templates with "
                               "vars: %s" % err)
                sys.exit(1)

        yaml = jenkins_template.generate_project(params, final_jobs)

        # write template
        tname = jenkins_template.template_name(repo)
        tpath = os.path.join(instance, tname)
        self.app.workspace.write_template(tpath, yaml)
        self.log.etc("\n======== Resulting YAML ========\n")
        self.log.etc(yaml + "\n")

    def execute(self, opts):
        self.clean_workspace(opts.workspace)
        self.copy_templates(opts.templates)
        user_params = params_from_str(opts.params)
        if bool(user_params):
            self.log.info("Injecting params: %s" % user_params)
        seen_instances = []  # memoize seen instances for subdir creation
        for repo, instances in self.repo_job_mapping(opts.repos,
                                                     opts.file_filter,
                                                     opts.force,
                                                     opts.api_url).iteritems():
            for instance, templates in instances.iteritems():
                if instance not in seen_instances:
                    self.app.workspace.create_subdir(instance)
                    seen_instances.append(instance)
                params = self.repo_params(instance, repo)
                params.update(user_params)
                self.write_instance_templates(instance,
                                              repo, params, templates)


class SyncCommand(GenerateTemplatesCommand):
    def configure_parser(self, parser):
        parser.add_argument("-i",
                            "--instances",
                            nargs="*",
                            default=[],
                            help="List of instances to sync. Defaults to ALL.")
        super(SyncCommand, self).configure_parser(parser)

    def description(self):
        return "Generate templates, apply them to Jenkins instances."

    def execute(self, opts):
        super(SyncCommand, self).execute(opts)
        seen_instances = []
        for repo, instances in self.repo_job_mapping(opts.repos,
                                                     opts.file_filter,
                                                     opts.force,
                                                     opts.api_url).iteritems():
            for instance in instances.keys():
                if instance in seen_instances:
                    continue
                if len(opts.instances) > 0:
                    if instance not in opts.instances:
                        continue
                seen_instances.append(instance)
                self.log.title("configuring [%s] (delegating to jenkins-job-"
                               "builder)" % instance)
                try:
                    icfg = self.app.config.jenkins.instances()[instance]
                except KeyError:
                    self.log.error("no such instance [%s] for"
                                   " [%s], skipping" % (instance, repo))
                    continue
                create_jobs(instance, self.app.workspace, icfg)


# TODO: refactor & care; this entire command is a hack.
class ProvisionLocalRepoCommand(GenerateTemplatesCommand):
    def configure_parser(self, parser):
        parser.add_argument("--api-url",
                            dest="api_url",
                            default=None,
                            help="Github API URL to use.")
        parser.add_argument("instance",
                            help="Jenkins instance to provision")
        parser.add_argument("templates",
                            nargs="*",
                            help="Templates to use.")
        parser.add_argument("--repo",
                            dest="repo",
                            default=None,
                            help="Repository to fetch metadata for. Use this"
                                 " if you don't want the cwd as the git repo")
        parser.add_argument("--template-vars",
                            dest="vars",
                            nargs="*",
                            default=[],
                            help="Variables to inject into specific templates."
                                 " In the following form"
                                 " (note no whitespace in JSON):\n"
                                 " <template_name>:{\"var\":[\"values\"]}")
        parser.add_argument("--fork",
                            type=str,
                            default="origin",
                            help="Fork to pull github data from")
        parser.add_argument("-p",
                            "--params",
                            nargs="*",
                            default=[],
                            help="List of params to inject (key:value)")
        parser.add_argument("-f",
                            "--force-sync",
                            dest="force",
                            action="store_true",
                            default=False,
                            help="Force repository sync, ignoring cache.")
        parser.add_argument("-w",
                            "--workspace",
                            dest="workspace",
                            type=str,
                            default=None,
                            help="prepare a target template directory")

    def _default_workspace(self, fork):
        return os.path.join(chap.app_home(), "workspace", "gh-sync", fork)

    def description(self):
        return "Provision a single job on an instance using templates files" \
               " in chamberlain's lib dirs"

    def execute(self, opts):
        try:
            icfg = self.app.config.jenkins.instances()[opts.instance]
        except KeyError:
            self.log.error("no such instance [%s]" % (opts.instance))
            return

        fork = opts.repo
        org = None
        if fork is None:
            fork = git.name_from_local_remote(opts.fork)
            org = git.org_from_name(fork)
        else:
            org, _ = opts.repo.split("/", 1)
        fork = fork.lower()
        org = org.lower()
        repo_name = fork.replace("%s/" % org, "")

        self.log.title("Fetching github data for %s (org: %s)" % (fork, org))

        repo = repo_hash(self.app.github(opts.api_url).repository(org,
                                                                  repo_name))

        self.log.title("Fetched metadata for %s" % fork)
        self.log.info(json.dumps(repo, indent=2))

        workspace = opts.workspace
        if workspace is None:
            workspace = self._default_workspace(fork)
        workspace = "%s-%i" % (workspace, int(time.time()))

        self.app.workspace.set_dir(workspace)
        self.clean_workspace(workspace)
        self.app.workspace.create_subdir(opts.instance)
        params = self.repo_params(opts.instance, fork, Config(repo))
        user_params = params_from_str(opts.params)
        if bool(user_params):
            self.log.info("Injecting params: %s" % user_params)
        params['name'] = '%s-project' % params['name']
        params.update(user_params)
        self.write_instance_templates(opts.instance, fork, params,
                                      opts.templates, opts.vars)
        ok = 0
        try:
            create_jobs(opts.instance, self.app.workspace, icfg,
                        self.app.workspace._default_libdir())
        except Exception as err:
            self.log.error("Could not provision jobs: %s" % err)
            ok = 1
        self.log.info("Project templates created in:")
        print(workspace)
        return ok


class ShowMappingCommand(OrgTemplatesCommand):
    def description(self):
        return "List repositories & their associated job templates."

    def execute(self, opts):
        # TODO: actually care how I'm doing this
        for repo, instances in self.repo_job_mapping(opts.repos,
                                                     opts.file_filter,
                                                     opts.force,
                                                     opts.api_url).iteritems():
            self.log.title(repo)
            for instance, templates in instances.iteritems():
                self.log.bold("\t%s" % instance)
                for template in templates:
                    self.log.info("\t\t- %s" % template)
