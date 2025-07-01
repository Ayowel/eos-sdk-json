#!/usr/bin/env python3
"""
Parse the Epic Games SDK's library to generate a JSON index of its declarations.
"""

import json
import logging
import os
import re

logger = logging.getLogger()
logger.setLevel(logging.WARNING)

DEFINES_IGNORE_LIST = set((
    'EOS_BUILD_PLATFORM_HEADER_BASE',
    'EOS_PREPROCESSOR_JOIN', 'EOS_PREPROCESSOR_JOIN_INNER',
    'EOS_PREPROCESSOR_TO_STRING', 'EOS_PREPROCESSOR_TO_STRING_INNER',
    'EOS_VERSION_STRING_AFTERCL', 'EOS_VERSION_STRING', 'EOS_VERSION_STRING_BASE',
    'EOS_VERSION_STRINGIFY', 'EOS_VERSION_STRINGIFY_2',

    'EOS_RESULT_VALUE', 'EOS_RESULT_VALUE_LAST', 'EOS_UI_KEY_CONSTANT',
    'EOS_UI_KEY_MODIFIER', 'EOS_UI_KEY_MODIFIER_LAST', 'EOS_UI_KEY_ENTRY_FIRST',
    'EOS_UI_KEY_ENTRY', 'EOS_UI_KEY_CONSTANT_LAST'
    ))

DIRECTIVES_IGNORE_LIST = (
    '#pragma',  '#include',
    '#if', '#else', '#endif', '#ifndef',
    '#undef', '#error'
)

def absorb_comment(lines, i, line = '/*'):
    """
    Get a comment string from a list of lines.
    This only works for multiline comments and only one multiline comment per line is supported.

    :param lines: The list of lines to process
    :param i: The index of the next line
    :param line: The content of the line where a comment's start was found
    """
    assert line.lstrip().startswith('/*')
    line = line[2:].lstrip('*').strip()
    last_comment = ''
    while '*/' not in line:
        line_content = line.lstrip('*').lstrip()
        if last_comment:
            last_comment = f"{last_comment}\n{line_content}"
        else:
            last_comment = line_content
        line = lines[i].strip()
        i += 1
    line = line.split('*/')[0].rstrip('*').strip()
    if last_comment:
        last_comment = f"{last_comment}\n{line}"
    else:
        last_comment = line
    return (i, last_comment.rstrip('\n'))

def absorb_directive(lines, i, line = '#'):
    """
    Get a directive string from a list of lines.

    :param lines: The list of lines to process
    :param i: The index of the next line
    :param line: The content of the line where a directive's start was found
    """
    directive = ''
    while line.rstrip('\n').endswith('\\'):
        directive += line.replace('\\\n', '\n')
        line = lines[i]
        i+=1
    return (i, directive + line)

def explode_parameters(line):
    """
    Turn a parameters string into an iterator over the line's parameters.
    The provided string should correspond to the charaters between the function's parenthesis.

    :param line: The parameters section of a function
    :return: An iterator over a list of param dicts with 'name' and 'type' keys
    """
    for param in line.split(','):
        param_splitted = param.strip().split(' ')
        param_name = param_splitted[-1]
        param_type = ' '.join(param_splitted[0:-1]).strip()
        yield dict(name = param_name, type = param_type)

def parse_define(content, i, line, comment = '', file = ''):
    """Extract a #define's content from a list of lines"""
    (i, def_lines) = absorb_directive(content, i, line)
    definfo = re.match('^#define[ \t]+(?P<defname>[^ \t(]+)([ \t(]*(?P<params>\\([^()])\\))?[ \t(](?P<expr>(.|\n)*)$', def_lines)
    assert definfo
    defname = definfo['defname'].strip()
    params = definfo['params'].strip() if definfo['params'] is not None else None
    expr = definfo['expr'].strip()
    return (i, dict(
            comment = comment,
            expression = expr,
            name = defname,
            parameters = params,
            source = file,
    ))

def parse_function(content, i, line, comment = '', file = ''):
    """Extract a function's signature from a list of lines"""
    _ = content
    funcinfo = re.match('^EOS_DECLARE_FUNC\\((?P<retval>[^)]+)\\) *(?P<funcname>[a-zA-Z0-9_]+)\\((?P<params>.*)\\);$', line)
    assert funcinfo
    retval = funcinfo['retval'].strip()
    funcname = funcinfo['funcname'].strip()
    params = funcinfo['params'].strip()
    return (i, dict(
        comment = comment,
        methodname_flat = funcname,
        params = [*explode_parameters(params)] if params not in ('void', '') else [],
        returntype = retval,
        source = file,
    ))

def parse_callback(content, i, line, comment = '', file = ''):
    """Extract a callback's signature from a list of lines"""
    _ = content
    cbinfo = re.match('^(EOS_DECLARE_CALLBACK\\(|EOS_DECLARE_CALLBACK_RETVALUE\\((?P<rettype>[^,]+), *)(?P<cbname>[a-zA-Z0-9_]+),?(?P<params>.*)\\);$', line)
    assert cbinfo
    rettype = cbinfo['rettype'].strip() if cbinfo['rettype'] is not None else 'void'
    cbname = cbinfo['cbname'].strip()
    params = cbinfo['params'].strip()
    return (i, dict(
        callbackname = cbname,
        comment = comment,
        params = [*explode_parameters(params)],
        returntype = rettype,
        source = file,
    ))

def parse_struct(content, i, line, comment = '', file = ''):
    """Extract a struct's signature from a list of lines"""
    structinfo = re.match('^EOS_STRUCT\\((?P<name>[a-zA-Z0-9_]+), *\\($', line)
    assert structinfo
    struct_attrs = []
    end_found = False
    last_comment = ''

    while i < len(content):
        line = content[i].strip()
        i += 1
        if line == '':
            continue
        if line == '));':
            end_found = True
            break

        if line == 'union':
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
                        fieldtype = f"union\n{union_content}\n\u007d",
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
            attribute_info = dict(
                comment = last_comment,
                name = declinfo['name'],
                recommended_value = None,
                type = declinfo['type'],
            )
            comment_info = re.search(': Set this to (?P<value>[^.\r\n]+)([.\r\n]|$)', last_comment)
            if comment_info:
                attribute_info['recommended_value'] = comment_info['value']
            else:
                del attribute_info['recommended_value']
            struct_attrs.append(attribute_info)
            last_comment = ''
    assert end_found

    return (i, dict(
        comment = comment,
        fields = struct_attrs,
        source = file,
        struct = structinfo['name'],
    ))

def parse_enum(content, i, line, comment = '', file = ''):
    """Extract an enum's content from a list of lines"""
    enuminfo = re.match('^EOS_ENUM\\((?P<name>[a-zA-Z0-9_]+), *$', line)
    assert enuminfo
    enum_name = enuminfo['name']
    enum_attrs = dict()

    last_enum_value = -1
    last_comment = ''
    end_found = False
    while i < len(content):
        line = content[i].strip()
        i += 1
        if line == '':
            continue
        if line == ');':
            end_found = True
            break

        is_comment = '/*' in line
        declinfo = re.match('^(?P<name>[a-zA-Z0-9_]+)( *= *(?P<value>[x0-9a-f()< ]+))?,?$', line)
        assert is_comment or declinfo
        if is_comment:
            (i, last_comment) = absorb_comment(content, i, line)
        elif declinfo:
            assert declinfo['name'] not in enum_attrs
            if declinfo['value'] is not None:
                last_enum_value = declinfo['value']
            else:
                last_enum_value = str(int(last_enum_value) + 1)
            enum_value = str(last_enum_value)
            enum_attrs[declinfo['name']] = dict(
                comment = last_comment,
                name = declinfo['name'],
                value = enum_value,
            )
            last_comment = ''
        else:
            last_comment = ''
    assert end_found
    return (i, dict(
        comment = comment,
        enumname = enum_name,
        source = file,
        values = enum_attrs,
    ))

def parse_ui_enum(i, line, comment = '', file = '', enum_last_index = 0):
    """Extract an ui enum's content from a list of lines"""
    if file == 'eos_ui_keys.h':
        valinfo = re.match('^(?P<macro>EOS_UI_KEY([_A-Z]+))\\((?P<prefix>[a-zA-Z0-9_]+), (?P<name>[a-zA-Z0-9_]+)(, (?P<value>.+))?\\)$', line)
        assert valinfo
        macro = valinfo['macro'].strip()
        prefix = valinfo['prefix'].strip()
        name = valinfo['name'].strip()
        value = valinfo['value'].strip() if valinfo['value'] is not None else None
        if value is None:
            assert macro in ('EOS_UI_KEY_ENTRY', 'EOS_UI_KEY_CONSTANT_LAST')
            enum_last_index += 1
            value = f"{enum_last_index}"
        if macro == 'EOS_UI_KEY_ENTRY_FIRST':
            enum_last_index = int(value)
        effective_name = prefix + name
        return (i, 'EOS_UI_EKeyCombination', enum_last_index, dict(
            comment = comment,
            name = effective_name,
            value = value,
        ))
    if file == 'eos_ui_buttons.h':
        valinfo = re.match('^(?P<macro>EOS_UI_KEY([_A-Z]+))\\((?P<prefix>[a-zA-Z0-9_]+), (?P<name>[a-zA-Z0-9_]+), (?P<value>.+)\\)$', line)
        assert valinfo
        macro = valinfo['macro'].strip()
        prefix = valinfo['prefix'].strip()
        name = valinfo['name'].strip()
        value = valinfo['value'].strip()
        effective_name = prefix + name
        return (i, 'EOS_UI_EInputStateButtonFlags', enum_last_index, dict(
            comment = comment,
            name = effective_name,
            value = value,
        ))
    assert False

def build_header_file_index(dir_path):
    """Load the content of all header files in a directory."""
    files_index = {}
    for path, dirs, files in os.walk(dir_path):
        dirs.sort()
        for file in sorted(files):
            assert file not in files_index
            if not file.endswith('.h'):
                continue
            with open(os.path.join(path, file), 'r', encoding='utf8') as handle:
                files_index[file] = handle.readlines()
    return files_index

def build_file_read_order(files_index):
    """From a list of header files, determine in which order they should be parsed."""
    # List includes for each files
    files_priority = dict()
    for file, content in files_index.items():
        includes = set()
        for line in content:
            if line.startswith('#include '):
                included = re.match('^#include +(?P<path>[^ ]+)$', line)
                assert included
                path = included['path'].strip()
                if path.startswith('"') and path.endswith('"'):
                    if path.endswith('.h"'):
                        assert path[1:-1] in files_index
                        includes.add(path[1:-1])
                elif (path.startswith('<') and path.endswith('>')) or re.match('^[a-zA-Z0-9_]+$', path):
                    pass
                else:
                    assert False
        files_priority[file] = includes

    # Sort in inclusion order
    files_order = []
    while files_priority:
        to_pop = []
        for filename, included_files in files_priority.items():
            new_v = included_files - set(files_order)
            if len(new_v) == 0:
                files_order.append(filename)
                to_pop.append(filename)
                continue
            if len(new_v) != len(included_files):
                files_priority[filename] = new_v
        for filename in to_pop:
            files_priority.pop(filename)

    return files_order

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
            enumname = 'EOS_EResult',
            values = dict(),
            source = 'eos_common.h',
        ),
        EOS_UI_EKeyCombination = dict(
            enumname = 'EOS_UI_EKeyCombination',
            source = 'eos_ui_keys.h',
            values = dict(),
        ),
        EOS_UI_EInputStateButtonFlags = dict(
            enumname = 'EOS_UI_EInputStateButtonFlags',
            source = 'eos_ui_buttons.h',
            values = dict(),
        ),
    )
    enum_last_index = 0

    # Index all headers
    files_index = build_header_file_index(dir_path)
    files_order = build_file_read_order(files_index)
    # Do not parse eos_base as it only profides multiple definitions of other defines
    assert 'eos_base.h' in files_order
    files_order.remove('eos_base.h')

    # Build API index
    for file in files_order:
        content = files_index[file]
        i = 0
        last_file_comment = ''
        while i < len(content):
            line = content[i]
            i += 1
            if not line.lstrip().startswith('/*'):
                last_file_comment = ''
            else:
                eof_reached = False
                while line.lstrip().startswith('/*'):
                    (i, last_file_comment) = absorb_comment(content, i, line)
                    if i >= len(content):
                        eof_reached = True
                        break
                    line = content[i]
                    i += 1
                if eof_reached:
                    continue

            if line.startswith('#define'):
                (i, definition) = parse_define(content, i, line, last_file_comment, file)
                assert definition['name'] not in defines
                if definition['name'] not in DEFINES_IGNORE_LIST:
                    defines[definition['name']] = definition

            elif line.startswith('EOS_DECLARE_FUNC'):
                (i, definition) = parse_function(content, i, line, last_file_comment, file)
                assert definition['methodname_flat'] not in functions
                functions[definition['methodname_flat']] = definition

            elif line.startswith('EOS_DECLARE_CALLBACK'):
                (i, definition) = parse_callback(content, i, line, last_file_comment, file)
                assert definition['callbackname'] not in callbacks
                callbacks[definition['callbackname']] = definition

            elif line.startswith('EOS_RESULT_VALUE'):
                valinfo = re.match('^EOS_RESULT_VALUE(_LAST)?\\((?P<name>[a-zA-Z0-9_]+), (?P<value>[x0-9A-F]+)\\)$', line)
                assert valinfo
                name = valinfo['name'].strip()
                value = valinfo['value'].strip()
                assert name not in enums['EOS_EResult']['values']
                enums['EOS_EResult']['values'][name] = dict(
                    comment = last_file_comment,
                    name = name,
                    value = value
                )

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
                (i, definition) = parse_struct(content, i, line, last_file_comment, file)
                assert definition['struct'] not in structs
                structs[definition['struct']] = definition

            elif line.startswith('EOS_ENUM_BOOLEAN_OPERATORS'):
                pass

            elif line.startswith('EOS_ENUM_START') or line.startswith('EOS_ENUM_END'):
                enuminfo = re.match('^EOS_ENUM_(START|END)\\((?P<name>[a-zA-Z_]+)\\);?$', line)
                assert enuminfo
                assert enuminfo['name'] in ('EOS_EResult', 'EOS_UI_EKeyCombination', 'EOS_UI_EInputStateButtonFlags')

            elif line.startswith('EOS_ENUM'):
                (i, definition) = parse_enum(content, i, line, last_file_comment, file)
                assert definition['enumname'] not in enums
                enums[definition['enumname']] = definition

            elif line.startswith('EOS_UI_'):
                (i, parent, enum_last_index, definition) = parse_ui_enum(i, line, last_file_comment, file, enum_last_index)
                assert definition['name'] not in enums[parent]['values']
                enums[parent]['values'][definition['name']] = definition

            elif line.startswith('typedef') or line.startswith('EOS_EXTERN_C'):
                definfo = re.match('^(?P<extern>EOS_EXTERN_C )?typedef (?P<type>.+) ((?P<name>[a-zA-Z0-9_]+)|(?P<signature>\\(.*\\* *(?P<name2>[a-zA-Z0-9_]+)\\)\\(.*\\)));$', line)
                assert definfo
                defname = definfo['name'] or definfo['name2'].strip()
                assert (defname) not in defines
                typedefs[defname] = dict(
                    comment = last_file_comment,
                    extern = definfo['extern'] is not None,
                    name = defname,
                    source = file,
                    type = definfo['type'].strip() + (
                        definfo['signature'].replace(
                            defname if f" {defname}" not in definfo['signature'] else f" {defname}", '', 1
                        ) if definfo['signature'] is not None else ''
                    ),
                )

            elif line.split(' ')[0].rstrip() in DIRECTIVES_IGNORE_LIST:
                (i, _) = absorb_directive(content, i, line)

            elif line.lstrip().startswith('//') or line.strip() == '':
                pass

            else:
                logger.error("Found unrecognized / unsupported prefix: %s", line)
                assert False

    return dict(
        callback_methods = [*callbacks.values()],
        defines = [*defines.values()],
        enums = [sort_dict(dict(values = [*v.pop('values').values()], **v)) for v in enums.values()],
        functions = [*functions.values()],
        structs = [*structs.values()],
        typedefs = [*typedefs.values()],
    )

def sort_list_items(data):
    """Helper function to sort alphabetically the dicts in a list"""
    return [
        sort_dict(l) if isinstance(l, dict) else (
            sort_list_items(l) if isinstance(l, (list, tuple)) else l
        ) for l in data
    ]

def sort_dict(data):
    """Helper function to input alphabetically the keys of a dict"""
    return dict(
        (k, sort_dict(v) if isinstance(v, dict) else (
            sort_list_items(v) if isinstance(v, (list, tuple)) else v
        )) for k, v in sorted(data.items())
    )

if __name__ == '__main__':
    import sys
    def main(sdk_dir, output_file, metadata = None):
        """Entrypoint"""
        assert os.path.isdir(sdk_dir)
        if output_file != '-':
            assert os.path.isdir(os.path.dirname(output_file))
        if not os.path.exists(os.path.join(sdk_dir, 'eos_common.h')):
            if not os.path.exists(os.path.join(sdk_dir, 'Include', 'eos_common.h')):
                if not os.path.exists(os.path.join(sdk_dir, 'SDK', 'Include', 'eos_common.h')):
                    logger.error('Could not find EOS C SDK in %s', sdk_dir)
                    return 1
                sdk_dir = os.path.join(sdk_dir, 'SDK')
            sdk_dir = os.path.join(sdk_dir, 'Include')

        json_index = dict()
        if metadata:
            json_index['metadata'] = sort_dict(metadata)
        json_index.update(index_sdk_directory(sdk_dir))
        index_string = json.dumps(json_index, indent = 2)

        if output_file == '-':
            print(index_string)
        else:
            with open(output_file, 'w', encoding = 'utf8') as file_handle:
                file_handle.write(index_string)
        return 0

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    if len(sys.argv) not in (3, 4) or '-h' in sys.argv or '--help' in sys.argv:
        logger.error("This script must be given the SDK path as first argument and the desired output file path as second argument")
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2], json.loads(sys.argv[3] if len(sys.argv) > 3 else '{}')) or 0)
