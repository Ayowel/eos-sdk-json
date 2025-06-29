#!/usr/bin/env python3
"""
Parse the Epic Games SDK's library to generate a JSON index of its declarations.
"""

import json
import re
import os

DEFINES_IGNORE_LIST = set((
    'EOS_BUILD_PLATFORM_HEADER_BASE', 'EOS_PREPROCESSOR_JOIN',
    'EOS_PREPROCESSOR_TO_STRING', 'EOS_PREPROCESSOR_TO_STRING_INNER',
    'EOS_VERSION_STRING_AFTERCL', 'EOS_VERSION_STRING', 'EOS_VERSION_STRING_BASE',
    'EOS_VERSION_STRINGIFY', 'EOS_VERSION_STRINGIFY_2',

    'EOS_RESULT_VALUE', 'EOS_RESULT_VALUE_LAST', 'EOS_UI_KEY_CONSTANT',
    'EOS_UI_KEY_MODIFIER', 'EOS_UI_KEY_MODIFIER_LAST', 'EOS_UI_KEY_ENTRY_FIRST',
    'EOS_UI_KEY_ENTRY', 'EOS_UI_KEY_CONSTANT_LAST'
    ))

def absorb_comment(lines, i, line = '/*'):
    assert line.startswith('/*')
    line = line[2:].lstrip('*').strip()
    last_comment = ''
    while '*/' not in line:
        line = lines[i].strip()
        i += 1
        line_content = line.lstrip('*').lstrip()
        if last_comment:
            last_comment = f"{last_comment}\n{line_content}"
        else:
            last_comment = line_content
    line = line.split('*/')[0].rstrip('*').strip()
    if last_comment:
        last_comment = f"{last_comment}\n{line}"
    else:
        last_comment = line
    return (i, last_comment)

def explode_parameters(line):
    for param in line.split(','):
        param_splitted = param.strip().split(' ')
        param_name = param_splitted[-1]
        param_type = ' '.join(param_splitted[0:-1]).strip()
        yield dict(name = param_name, type = param_type)

def index_sdk_directory(dir_path):
    """
    Parse the Epic Games SDK's library to generate an index of its declarations.
    """
    defines = {}
    functions = {}
    callbacks = {}
    structs = {}
    typedefs = {}
    enums = dict(
        EOS_EResult = dict(
            values = dict(),
            source = 'eos_common.h',
        ),
        EOS_UI_EKeyCombination = dict(
            source = 'eos_ui_keys.h',
            values = dict(),
        ),
        EOS_UI_EInputStateButtonFlags = dict(
            source = 'eos_ui_buttons.h',
            values = dict(),
        ),
    )
    enum_last_index = 0
    files_index = dict()
    for path, dirs, files in os.walk(dir_path):
        dirs.sort()
        for f in sorted(files):
            assert f not in files_index
            if not f.endswith('.h'):
                continue
            with open(os.path.join(path, f), 'r', encoding='utf8') as h:
                # content = h.readlines()
                files_index[f] = h.readlines()

    # List includes for each files
    files_priority = dict()
    for f, content in files_index.items():
        includes = set()
        for l in content:
            if l.startswith('#include '):
                included = re.match('^#include +(?P<path>[^ ]+)$', l)
                assert included
                path = included['path'].strip()
                if path.startswith('"') and path.endswith('"'):
                    if path.endswith('.h"'):
                        assert path[1:-1] in files_index
                        includes.add(path[1:-1])
                elif path.startswith('<') and path.endswith('>'):
                    pass
                elif re.match('^[a-zA-Z0-9_]+$', path):
                    pass
                else:
                    assert False
        files_priority[f] = includes

    # Sort in inclusion order
    files_order = list()
    while files_priority:
        to_pop = list()
        for k, v in files_priority.items():
            new_v = v - set(files_order)
            if len(new_v) == 0:
                files_order.append(k)
                to_pop.append(k)
                continue
            if len(new_v) != len(v):
                files_priority[k] = new_v
        for k in to_pop:
            files_priority.pop(k)

    # Do not parse eos_base as it only profides multiple definitions of other defines
    assert 'eos_base.h' in files_order
    files_order.remove('eos_base.h')

    # Build API index
    for f in files_order:
        content = files_index[f]
        i = 0
        last_file_comment = ''
        while i < len(content):
            line = content[i]
            i += 1
            if not line.startswith('/*'):
                last_file_comment = ''
            else:
                eof_reached = False
                while line.startswith('/*'):
                    (i, last_file_comment) = absorb_comment(content, i, line)
                    if i >= len(content):
                        eof_reached = True
                        break
                    line = content[i]
                    i += 1
                if eof_reached:
                    continue

            if line.startswith('#define'):
                definfo = re.match('^#define[ \t]+(?P<defname>[^ \t(]+)([ \t(]*(?P<params>\\([^()])\\))?[ \t(](?P<expr>.*)$', line)
                assert definfo
                defname = definfo['defname'].strip()
                params = definfo['params'].strip() if definfo['params'] is not None else None
                expr = definfo['expr'].strip()
                assert defname not in defines
                if defname not in DEFINES_IGNORE_LIST:
                    defines[defname] = dict(
                        comment = last_file_comment,
                        expression = expr,
                        name = defname,
                        parameters = params,
                        source = f,
                    )

            elif line.startswith('EOS_DECLARE_FUNC'):
                funcinfo = re.match('^EOS_DECLARE_FUNC\\((?P<retval>[^)]+)\\) *(?P<funcname>[a-zA-Z0-9_]+)\\((?P<params>.*)\\);$', line)
                assert funcinfo
                retval = funcinfo['retval'].strip()
                funcname = funcinfo['funcname'].strip()
                params = funcinfo['params'].strip()
                assert funcname not in functions
                functions[funcname] = dict(
                    comment = last_file_comment,
                    methodname_flat = funcname,
                    params = [*explode_parameters(params)] if params != 'void' and params != '' else [],
                    returntype = retval,
                    source = f,
                )

            elif line.startswith('EOS_DECLARE_CALLBACK'):
                cbinfo = re.match('^(EOS_DECLARE_CALLBACK\\(|EOS_DECLARE_CALLBACK_RETVALUE\\((?P<rettype>[^,]+), *)(?P<cbname>[a-zA-Z0-9_]+),?(?P<params>.*)\\);$', line)
                assert cbinfo
                rettype = cbinfo['rettype'].strip() if cbinfo['rettype'] is not None else 'void'
                cbname = cbinfo['cbname'].strip()
                params = cbinfo['params'].strip()
                assert cbname not in callbacks
                callbacks[cbname] = dict(
                    callbackname = cbname,
                    comment = last_file_comment,
                    params = [*explode_parameters(params)],
                    returntype = rettype,
                    source = f,
                )

            elif line.startswith('EOS_RESULT_VALUE'):
                valinfo = re.match('^EOS_RESULT_VALUE(_LAST)?\\((?P<name>[a-zA-Z0-9_]+), (?P<value>[x0-9A-F]+)\\)$', line)
                assert valinfo
                name = valinfo['name'].strip()
                value = valinfo['value'].strip()
                assert name not in enums['EOS_EResult']['values']
                enums['EOS_EResult']['values'][name] = value

            elif line.startswith('EOS_DECLARE_CALLBACK_RETVALUE'):
                callbackinfo = re.match('^EOS_DECLARE_CALLBACK_RETVALUE\\((?P<rettype>[^),]+) (?P<name>[^),]+)(?P<params>,[^)]+)\\)', line)
                assert callbackinfo
                assert callbackinfo['name'] not in callbacks
                callbacks[callbackinfo['name']] = dict(
                    comment = last_file_comment,
                    params = [p.strip() for p in callbackinfo['params'].lstrip(',').split(',')],
                    rettype = callbackinfo['rettype'],
                )

            elif line.startswith('EOS_STRUCT'):
                structinfo = re.match('^EOS_STRUCT\\((?P<name>[a-zA-Z0-9_]+), *\\($', line)
                assert structinfo
                struct_name = structinfo['name']
                struct_attrs = list()
                end_found = False
                last_comment = ''

                while i < len(content):
                    line = content[i].strip()
                    i += 1
                    if line == '':
                        continue
                    elif line == '));':
                        end_found = True
                        break
                    elif line == 'union':
                        union_content = ''
                        while i < len(content):
                            line = content[i].strip()
                            i += 1
                            if line.startswith('}'):
                                lineinfo = re.match('^} (?P<name>[a-zA-Z_]+);$', line)
                                assert lineinfo
                                struct_attrs.append(dict(
                                    fieldcomment = last_comment,
                                    fieldname = lineinfo['name'],
                                    fieldtype = "union\n%s\n}" % union_content,
                                ))
                                last_comment = ''
                                break
                            union_content = f"{union_content}\n{line}"
                        continue

                    is_comment = line.startswith('/*')
                    declinfo = re.match('^(?P<type>.*) (?P<name>[a-zA-Z0-9_[\\]]+);', line)
                    assert is_comment or declinfo
                    if is_comment:
                        (i, last_comment) = absorb_comment(content, i, line)
                    elif declinfo:
                        struct_attrs.append(dict(
                            comment = last_comment,
                            name = declinfo['name'],
                            type = declinfo['type'],
                        ))
                        last_comment = ''
                assert end_found

                structs[struct_name] = dict(
                    comment = last_file_comment,
                    fields = struct_attrs,
                    source = f,
                    struct = struct_name,
                )

            elif line.startswith('EOS_ENUM_BOOLEAN_OPERATORS'):
                pass
            elif line.startswith('EOS_ENUM_START') or line.startswith('EOS_ENUM_END'):
                enuminfo = re.match('^EOS_ENUM_(START|END)\\((?P<name>[a-zA-Z_]+)\\);?$', line)
                assert enuminfo
                assert enuminfo['name'] in ('EOS_EResult', 'EOS_UI_EKeyCombination', 'EOS_UI_EInputStateButtonFlags')
            elif line.startswith('EOS_ENUM'):
                enuminfo = re.match('^EOS_ENUM\\((?P<name>[a-zA-Z0-9_]+), *$', line)
                assert enuminfo
                enum_name = enuminfo['name']
                enum_attrs = dict()
                assert enum_name not in enums

                last_enum_value = -1
                while i < len(content):
                    line = content[i].strip()
                    i += 1
                    if line == '':
                        continue
                    elif line == ');':
                        end_found = True
                        break
                    is_comment = '/*' in line
                    declinfo = re.match('^(?P<name>[a-zA-Z0-9_]+)( *= *(?P<value>[x0-9a-f()< ]+))?,?$', line)
                    assert is_comment or declinfo
                    if is_comment:
                        (i, _) = absorb_comment(content, i, line)
                    elif declinfo:
                        assert declinfo['name'] not in enum_attrs
                        if declinfo['value'] is not None:
                            last_enum_value = declinfo['value']
                        else:
                            last_enum_value = str(int(last_enum_value) + 1)
                        enum_value = str(last_enum_value)
                        enum_attrs[declinfo['name']] = enum_value
                enums[enum_name] = dict(
                    source = f,
                    values = enum_attrs,
                )

            elif line.startswith('EOS_UI_'):
                if f == 'eos_ui_keys.h':
                    valinfo = re.match('^(?P<macro>EOS_UI_KEY([_A-Z]+))\\((?P<prefix>[a-zA-Z0-9_]+), (?P<name>[a-zA-Z0-9_]+)(, (?P<value>.+))?\\)$', line)
                    assert valinfo
                    macro = valinfo['macro'].strip()
                    prefix = valinfo['prefix'].strip()
                    name = valinfo['name'].strip()
                    value = valinfo['value'].strip() if valinfo['value'] is not None else None
                    if value is None:
                        assert macro == 'EOS_UI_KEY_ENTRY' or macro == 'EOS_UI_KEY_CONSTANT_LAST'
                        enum_last_index += 1
                        value = f"{enum_last_index}"
                    if macro == 'EOS_UI_KEY_ENTRY_FIRST':
                        enum_last_index = int(value)
                    effective_name = prefix + name
                    assert effective_name not in enums['EOS_UI_EKeyCombination']['values']
                    enums['EOS_UI_EKeyCombination']['values'][effective_name] = value
                elif f == 'eos_ui_buttons.h':
                    valinfo = re.match('^(?P<macro>EOS_UI_KEY([_A-Z]+))\\((?P<prefix>[a-zA-Z0-9_]+), (?P<name>[a-zA-Z0-9_]+), (?P<value>.+)\\)$', line)
                    assert valinfo
                    macro = valinfo['macro'].strip()
                    prefix = valinfo['prefix'].strip()
                    name = valinfo['name'].strip()
                    value = valinfo['value'].strip()
                    effective_name = prefix + name
                    assert effective_name not in enums['EOS_UI_EInputStateButtonFlags']['values']
                    enums['EOS_UI_EInputStateButtonFlags']['values'][effective_name] = value
                else:
                    assert False

            elif line.startswith('typedef') or line.startswith('EOS_EXTERN_C'):
                definfo = re.match('^(?P<extern>EOS_EXTERN_C )?typedef (?P<type>.+) ((?P<name>[a-zA-Z0-9_]+)|(?P<signature>\\(.*\\* *(?P<name2>[a-zA-Z0-9_]+)\\)\\(.*\\)));$', line)
                assert definfo
                defname = definfo['name'] or definfo['name2'].strip()
                assert (defname) not in defines
                typedefs[defname] = dict(
                    comment = last_file_comment,
                    extern = definfo['extern'] is not None,
                    name = defname,
                    source = f,
                    type = definfo['type'].strip() + (definfo['signature'].replace(defname if f" {defname}" not in definfo['signature'] else f" {defname}", '', 1) if definfo['signature'] is not None else ''),
                )

            else:
                pass

    return dict(
        callback_methods = [*callbacks.values()],
        defines = [*defines.values()],
        enums = [dict(
            enumname = n,
            source = v['source'],
            values = [{"name": vk, "value": vv} for vk, vv in v['values'].items()],
            ) for n,v in enums.items()],
        functions = [*functions.values()],
        structs = [*structs.values()],
        typedefs = [*typedefs.values()],
    )

if __name__ == '__main__':
    import sys
    def main(sdk_dir, output_file):
        """Entrypoint"""
        assert os.path.isdir(sdk_dir)
        if output_file != '-':
            assert os.path.isdir(os.path.dirname(output_file))
        if not os.path.exists(os.path.join(sdk_dir, 'eos_common.h')):
            if not os.path.exists(os.path.join(sdk_dir, 'Include', 'eos_common.h')):
                if not os.path.exists(os.path.join(sdk_dir, 'SDK', 'Include', 'eos_common.h')):
                    print(f'Could not find EOS C SDK in {sdk_dir}')
                    return 1
                sdk_dir = os.path.join(sdk_dir, 'SDK')
            sdk_dir = os.path.join(sdk_dir, 'Include')

        json_index = index_sdk_directory(sdk_dir)
        index_string = json.dumps(json_index, indent = 2)

        if output_file == '-':
            print(index_string)
        else:
            with open(output_file, 'w', encoding = 'utf8') as f:
                f.write(index_string)

    if len(sys.argv) != 3 or '-h' in sys.argv or '--help' in sys.argv:
        print("This script must be given the SDK path as first argument and the desired output file path as second argument")
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]) or 0)
