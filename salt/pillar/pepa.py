#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Configuration templating using Hierarchical substitution and Jinja.

Documentation: https://github.com/mickep76/pepa
'''

__author__ = 'Michael Persson <michael.ake.persson@gmail.com>'
__copyright__ = 'Copyright (c) 2013 Michael Persson'
__license__ = 'Apache License, Version 2.0'
__version__ = '0.6.4'

# Import python libs
import logging
import sys
import yaml
import jinja2
import re


# Only used when called from a terminal
log = None
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('hostname', help='Hostname')
    parser.add_argument('-c', '--config', default='/etc/salt/master', help='Configuration file')
    parser.add_argument('-d', '--debug', action='store_true', help='Print debug info')
    parser.add_argument('-g', '--grains', help='Input Grains as YAML')
    parser.add_argument('-p', '--pillar', help='Input Pillar as YAML')
    parser.add_argument('-n', '--no-color', action='store_true', help='No color output')
    args = parser.parse_args()

    LOG_LEVEL = logging.WARNING
    if args.debug:
        LOG_LEVEL = logging.DEBUG

    formatter = None
    if not args.no_color:
        try:
            import colorlog
            formatter = colorlog.ColoredFormatter("[%(log_color)s%(levelname)-8s%(reset)s] %(log_color)s%(message)s%(reset)s")
        except ImportError:
            formatter = logging.Formatter("[%(levelname)-8s] %(message)s")
    else:
        formatter = logging.Formatter("[%(levelname)-8s] %(message)s")

    stream = logging.StreamHandler()
    stream.setLevel(LOG_LEVEL)
    stream.setFormatter(formatter)

    log = logging.getLogger('pythonConfig')
    log.setLevel(LOG_LEVEL)
    log.addHandler(stream)
else:
    log = logging.getLogger(__name__)


# Options
__opts__ = {
    'pepa_roots': {
        'base': '/srv/salt'
    },
    'pepa_delimiter': '..'
}

try:
    from os.path import isfile, join
    HAS_OS_PATH = True
except ImportError:
    HAS_OS_PATH = False


def __virtual__():
    '''
    Only return if all the modules are available
    '''
    if not HAS_OS_PATH:
        return False

    return True


def key_value_to_tree(data):
    '''
    Convert key/value to tree
    '''
    tree = {}
    for flatkey, value in data.items():
        t = tree
        keys = flatkey.split(__opts__['pepa_delimiter'])
        for key in keys:
            if key == keys[-1]:
                t[key] = value
            else:
                t = t.setdefault(key, {})
    return tree


def ext_pillar(minion_id, pillar, resource, sequence, subkey=False, subkey_only=False):
    '''
    Evaluate Pepa templates
    '''
    roots = __opts__['pepa_roots']

    # Default input
    inp = {}
    inp['default'] = 'default'
    inp['hostname'] = minion_id

    if 'environment' in pillar:
        inp['environment'] = pillar['environment']
    elif 'environment' in __grains__:
        inp['environment'] = __grains__['environment']
    else:
        inp['environment'] = 'base'

    # Load templates
    output = inp
    output['pepa_templates'] = []
    immutable = {}

    for categ, info in [s.items()[0] for s in sequence]:
        if categ not in inp:
            log.warn("Category is not defined: {0}".format(categ))
            continue

        alias = None
        if isinstance(info, dict) and 'name' in info:
            alias = info['name']
        else:
            alias = categ

        templdir = None
        if info and 'base_only' in info and info['base_only']:
            templdir = join(roots['base'], resource, alias)
        else:
            templdir = join(roots[inp['environment']], resource, alias)

        entries = []
        if isinstance(inp[categ], list):
            entries = inp[categ]
        elif not inp[categ]:
            log.warn("Category has no value set: {0}".format(categ))
            continue
        else:
            entries = [inp[categ]]

        for entry in entries:
            results = None
            fn = join(templdir, re.sub(r'\W', '_', entry.lower()) + '.yaml')
            if isfile(fn):
                log.info("Loading template: {0}".format(fn))
                template = jinja2.Template(open(fn).read())
                output['pepa_templates'].append(fn)
                data = key_value_to_tree(output)
                data['grains'] = __grains__.copy()
                data['pillar'] = pillar.copy()
                results = yaml.load(template.render(data))
            else:
                log.info("Template doesn't exist: {0}".format(fn))
                continue

            if results is not None:
                for key in results:
                    skey = key.rsplit(__opts__['pepa_delimiter'], 1)
                    rkey = None
                    operator = None
                    if len(skey) > 1 and key.rfind('()') > 0:
                        rkey = skey[0].rstrip(__opts__['pepa_delimiter'])
                        operator = skey[1]

                    if key in immutable:
                        log.warning('Key {0} is immutable, changes are not allowed'.format(key))
                    elif rkey in immutable:
                        log.warning("Key {0} is immutable, changes are not allowed".format(rkey))
                    elif operator == 'merge()':
                        log.debug("Merge key {0}: {1}".format(rkey, results[key]))
                        if rkey in output and type(results[key]) != type(output[rkey]):
                            log.warning('You can''t merge different types for key {0}'.format(rkey))
                        elif type(results[key]) is dict:
                            output[rkey].update(results[key])
                        elif type(results[key]) is list:
                            output[rkey].extend(results[key])
                        else:
                            log.warning('Unsupported type need to be list or dict for key {0}'.format(rkey))
                    elif operator == 'unset()':
                        log.debug("Unset key {0}".format(rkey))
                        try:
                            del output[rkey]
                        except KeyError:
                            pass
                    elif operator == 'immutable()':
                        log.debug("Set immutable and substitute key {0}: {1}".format(rkey, results[key]))
                        immutable[rkey] = True
                        output[rkey] = results[key]
                    elif operator == 'imerge()':
                        log.debug("Set immutable and merge key {0}: {1}".format(rkey, results[key]))
                        immutable[rkey] = True
                        if rkey in output and type(results[key]) != type(output[rkey]):
                            log.warning('You can''t merge different types for key {0}'.format(rkey))
                        elif type(results[key]) is dict:
                            output[rkey].update(results[key])
                        elif type(results[key]) is list:
                            output[rkey].extend(results[key])
                        else:
                            log.warning('Unsupported type need to be list or dict for key {0}'.format(rkey))
                    elif operator == 'iunset()':
                        log.debug("Set immutable and unset key {0}".format(rkey))
                        immutable[rkey] = True
                        try:
                            del output[rkey]
                        except KeyError:
                            pass
                    elif operator is not None:
                        log.warning('Unsupported operator {0}, skipping key {1}'.format(operator, rkey))
                    else:
                        log.debug("Substitute key {0}: {1}".format(key, results[key]))
                        output[key] = results[key]

    tree = key_value_to_tree(output)
    pillar_data = {}
    if subkey_only:
        pillar_data[resource] = tree.copy()
    elif subkey:
        pillar_data = tree
        pillar_data[resource] = tree.copy()
    else:
        pillar_data = tree
    return pillar_data


def validate(output, resource):
    '''
    Validate Pepa templates
    '''
    try:
        import cerberus
    except ImportError:
        log.critical('You need module cerberus in order to use validation')
        return

    roots = __opts__['pepa_roots']

    valdir = join(roots['base'], resource, 'validate')

    all_schemas = {}
    pepa_schemas = []
    for fn in glob.glob(valdir + '/*.yaml'):
        log.info("Loading schema: {0}".format(fn))
        template = jinja2.Template(open(fn).read())
        data = output
        data['grains'] = __grains__.copy()
        data['pillar'] = __pillar__.copy()
        schema = yaml.load(template.render(data))
        all_schemas.update(schema)
        pepa_schemas.append(fn)

    val = cerberus.Validator()
    if not val.validate(output['pepa_keys'], all_schemas):
        for ekey, error in val.errors.items():
            log.warning('Validation failed for key {0}: {1}'.format(ekey, error))

    output['pepa_schema_keys'] = all_schemas
    output['pepa_schemas'] = pepa_schemas


# Only used when called from a terminal
if __name__ == '__main__':
    # Load configuration file
    if not isfile(args.config):
        log.critical("Configuration file doesn't exist: {0}".format(args.config))
        sys.exit(1)

    # Get configuration
    __opts__.update(yaml.load(open(args.config).read()))

    loc = 0
    for name in [e.keys()[0] for e in __opts__['ext_pillar']]:
        if name == 'pepa':
            break
        loc += 1

    # Get grains
    __grains__ = {}
    if 'pepa_grains' in __opts__:
        __grains__ = __opts__['pepa_grains']
    if args.grains:
        __grains__.update(yaml.load(args.grains))

    # Get pillars
    __pillar__ = {}
    if 'pepa_pillar' in __opts__:
        __pillar__ = __opts__['pepa_pillar']
    if args.pillar:
        __pillar__.update(yaml.load(args.pillar))

    # Print results
    result = ext_pillar(args.hostname, __pillar__, __opts__['ext_pillar'][loc]['pepa']['resource'], __opts__['ext_pillar'][loc]['pepa']['sequence'])

    yaml.dumper.SafeDumper.ignore_aliases = lambda self, data: True
    if not args.no_color:
        try:
            import pygments
            import pygments.lexers
            import pygments.formatters
            print pygments.highlight(yaml.safe_dump(result), pygments.lexers.YamlLexer(), pygments.formatters.TerminalFormatter())
        except ImportError:
            print yaml.safe_dump(result, indent=4, default_flow_style=False)
    else:
        print yaml.safe_dump(result, indent=4, default_flow_style=False)