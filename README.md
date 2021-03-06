Chamberlain
====

Automated Jenkins configuration for your GitHub repos.

Libs Used:

- [github3.py](https://github.com/sigmavirus24/github3.py) to gather repo data.
- [Jenkins Job Builder](https://github.com/openstack-infra/jenkins-job-builder) to configure Jenkins.

## Installation

```
git clone git@github.com:behance/chamberlain.git
cd chamberlain
sudo python setup.py install
```

## Configuration

**lives in `~/.chamberlain/config.json`, automatically created if DNE**

**Example:**

```ruby
{
    "github": {
        "auth": {
            "token": "your_oauth_token"
        },
        "orgs": [
            "behanceops"
        ]
    },
    "jenkins": {
        "instances": {
            "bejankins": {
                "jenkins": {
                    "url": "http://bejankins.net:8080",
                    "user": "behance-qe",
                    "password": "password"
                },
                "job_builder": {
                    "ignore_cache": "true"
                }
            }
        },
        "template_params": {
            "bejankins": {
                "gitauth": "aaaaaaaa-0000-aaaa-0000-aaaaaaaaaaaa",
                "ghprauth": "00000000-aaaa-0000-aaaa-000000000000"
            }
        },
        "jobs": [
            {
                "instance": "ci-jenkins",
                "owner": "behanceops",
                "repo": "bephp",
                "templates": [
                    "{repo}-integrations"
                ]
            },
            {
                "instance": "bejankins",
                "owner": "behanceops",
                "templates": [
                    "branch-cookbook-{repo}",
                    "master-cookbook-{repo}"
                ],
                "exclude": [
                    "misc"
                ]
            }
        ]
    }
}
```

**NOTE**: all values in the `instances` config should be strings. Also, the config values mirror the [configuration file for jenkins job builder](http://docs.openstack.org/infra/jenkins-job-builder/execution.html#configuration-file).

i.e.:

```ruby
  ...

            "bejankins": {
                "jenkins": {
                    "url": "http://bejankins.net:8080",
                    "user": "behance-qe",
                    "password": "password"
                },
                "job_builder": {
                    "ignore_cache": "true"
                }
            }

  ...
```

is the equivalent of this in Jenkins Job Builder:

```
[job_builder]
ignore_cache=True

[jenkins]
user=behance-qe
password=password
url=http://bejankins.net:8080
```

Default values for these configs can be found in the `chamberlain.jenkins.configuration` module.

## Usage

##### Universal Flags
- `--force-sync`, `-f` : pull repo data from github instead of referencing the cached list of repositories in `~/.chamberlain/github_repos.json`.

##### Universal Args
- `repos` : list of repositories to perform actions on.

*e.g.*: `chamberlain generate behance/repo1 matcher_word`

Internally, the list of repos that is generated for the commands to use will be filtered based on partial matches for `behance/repo1` and `matcher_word`

Can also be a regex.

## Commands

### **`chamberlain map [REPO1 REPO2 ...]`**
show github repositories and what job templates each one is associated with, or which job templates are associated with the given repos.

*this command caches its results in `~/.chamberlain/github_repos.json`*

### **`chamberlain generate [REPO1 REPO2 ...]`**

##### Flags
```
  -t, --templates   list of directories containing templates (default: [ cwd() ]
  -w, --workspace   prepare a target template directory
```

WARNING: this will wipe the given `--workspace` clean.
Given directories with YAML templates, prepares a workspace and generates project-template YAML files in the workspace.

The resulting workspace will look like:
```
workspace/
         jenkins_instance1/
         jenkins_instance2/
         templates/
```

`templates` will contain all template files that are passed in (either `cwd()` or the list of directories from `--templates`). The directories for the instances will contain all template files and project files for your repositories.

All project files are given 3 parameters:
- `name`: `<INSTANCE>-<REPO_FULLNAME>`
- `repo`: repository shortname
- `sshurl`: github SSH url

### **`chamberlain sync [REPO1 REPO2 ...]`**
Generates the workspace (using the same procedure as the `generate` command) and runs [Jenkins Job Builder](https://github.com/openstack-infra/jenkins-job-builder) in the application workspace, which defaults to `~/.chamberlain/workspace`

Same flags as the `generate` command.

### **`chamberlain gh-sync TEMPLATE_NAME INSTANCE_NAME`**

When run within a git repository, this command will attempt to take a bunch of github metdata for the repository and inject it into the given `TEMPLATE_NAME`. Immediately after on success, `INSTANCE_NAME` will be provisioned with the job.

Metadata fields that are automatically fetched and injected are:

```
    ghurl: https://github.com/behance/chamberlain
    jobs: ['{owner}-{repo}-make-ci']              # this is automatically updated as a list
    name: ci-jenkins-behance/chamberlain-project  # automatically generated
    owner: behance
    repo: chamberlain
    repo_full_name: behance/chamberlain
    sshurl: git@github.com:behance/chamberlain.git
```

Notice that in the example config, there is a section in the `jenkins` config called `template_params`. You can add default values in here to be injected into the hash above. These are overrides that will be injected **on top of** the hash above. This is specifically useful when you have credential IDs that you want to inject into your templates to use with things such as the [`Git SCM Plugin`](http://docs.openstack.org/infra/jenkins-job-builder/scm.html?highlight=git%20scm#scm.git)

Any other one-off overrides can be injected via the `--params` flag in the form of `key:value`

## Contributing
- make your changes
- `pip install tox && tox`

If you have docker install and do not want to install python libs you can just run

```
make ci
```

to run the tests in docker
