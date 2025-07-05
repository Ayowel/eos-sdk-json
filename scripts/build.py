#!/usr/bin/env python3
"""
Parse the Epic Games SDK's library to generate a JSON index of its declarations.
"""

from collections import OrderedDict
from functools import partial
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

def absorb_directive(lines, i, line = '#', comment = '', file = None):
    """
    Get a directive string from a list of lines.

    :param lines: The list of lines to process
    :param i: The index of the next line
    :param line: The content of the line where a directive's start was found
    """
    _ = (comment, file)
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
        yield OrderedDict(name = param_name, type = param_type)

def parse_define(content, i, line, comment = '', file = ''):
    """Extract a #define's content from a list of lines"""
    (i, def_lines) = absorb_directive(content, i, line)
    definfo = re.match('^#define[ \t]+(?P<defname>[^ \t(]+)([ \t(]*(?P<params>\\([^()])\\))?[ \t(](?P<expr>(.|\n)*)$', def_lines)
    assert definfo
    defname = definfo['defname'].strip()
    params = definfo['params'].strip() if definfo['params'] is not None else None
    expr = definfo['expr'].strip()
    return (i, OrderedDict(
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
    return (i, OrderedDict(
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
    return (i, OrderedDict(
        callbackname = cbname,
        comment = comment,
        params = [*explode_parameters(params)],
        returntype = rettype,
        source = file,
    ))

def parse_struct_union(content, i, line, comment = ''):
    """Extract a struct's union's signature from a list of lines"""
    assert line.strip() == 'union'
    assert content[i].strip() == '{'
    i += 1

    union = OrderedDict(
        comment = comment,
        name = '',
        type = '',
        unionitems = [],
    )
    union_content = ''

    while i < len(content):
        line = content[i].strip()
        i += 1
        last_comment = ''
        if line.lstrip().startswith('/*'):
            while line.lstrip().startswith('/*'):
                (i, last_comment) = absorb_comment(content, i, line)
                if i >= len(content):
                    i += 1
                    break
                line = content[i]
                i += 1
            if i > len(content):
                continue

        if line == '':
            continue

        if line.startswith('}'):
            lineinfo = re.match('^} (?P<name>[a-zA-Z_]+);$', line)
            assert lineinfo
            union['name'] = lineinfo['name']
            union['type'] = f"union\n{union_content}\n\u007d"
            return (i, union)

        union_content = f"{union_content}\n{line}"

        declinfo = re.match('^(?P<type>.*) (?P<name>[a-zA-Z0-9_[\\]]+);', line)
        assert declinfo is not None
        attribute_info = OrderedDict(
            comment = last_comment,
            name = declinfo['name'].strip(),
            recommended_value = None,
            type = declinfo['type'].strip(),
        )
        comment_info = re.search(': Set this to (?P<value>[^.\r\n]+)([.\r\n]|$)', last_comment)
        if comment_info:
            attribute_info['recommended_value'] = comment_info['value']
        else:
            del attribute_info['recommended_value']
        union['unionitems'].append(attribute_info)

    raise Exception('Reached end of file without exiting union context')

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
            (i, union) = parse_struct_union(content, i, line, comment)
            struct_attrs.append(union)
            continue

        is_comment = line.startswith('/*')
        declinfo = re.match(r'^(?P<type>.*) (?P<name>[a-zA-Z0-9_]+)(?P<arrayinfo>\[[A-Za-z0-9_]+\])?;', line)
        assert is_comment or declinfo
        if is_comment:
            (i, last_comment) = absorb_comment(content, i, line)
        elif declinfo:
            attribute_info = OrderedDict(
                comment = last_comment,
                name = declinfo['name'],
                recommended_value = None,
                type = declinfo['type']+(declinfo['arrayinfo'] or ''),
            )
            comment_info = re.search(': Set this to (?P<value>[^.\r\n]+)([.\r\n]|$)', last_comment)
            if comment_info:
                attribute_info['recommended_value'] = comment_info['value']
            else:
                del attribute_info['recommended_value']
            struct_attrs.append(attribute_info)
            last_comment = ''
    assert end_found

    return (i, OrderedDict(
        comment = comment,
        fields = struct_attrs,
        source = file,
        struct = structinfo['name'],
    ))

def parse_result_value(content, i, line, comment = '', file = ''):
    """Extract an EOS_RESULT enum value from a list of lines"""
    _ = (content, file)
    valinfo = re.match('^EOS_RESULT_VALUE(_LAST)?\\((?P<name>[a-zA-Z0-9_]+), (?P<value>[x0-9A-F]+)\\)$', line)
    assert valinfo
    name = valinfo['name'].strip()
    value = valinfo['value'].strip()
    return (i, OrderedDict(
        comment = comment,
        name = name,
        value = value
    ))

def parse_enum(content, i, line, comment = '', file = ''):
    """Extract an enum's content from a list of lines"""
    enuminfo = re.match('^EOS_ENUM\\((?P<name>[a-zA-Z0-9_]+), *$', line)
    assert enuminfo
    enum_name = enuminfo['name']
    enum_attrs = OrderedDict()

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
            enum_attrs[declinfo['name']] = OrderedDict(
                comment = last_comment,
                name = declinfo['name'],
                value = enum_value,
            )
            last_comment = ''
        else:
            last_comment = ''
    assert end_found
    return (i, OrderedDict(
        comment = comment,
        enumname = enum_name,
        source = file,
        values = enum_attrs,
    ))

def parse_enum_start_end(content, i, line, comment = '', file = ''):
    """Extract an enum start's name"""
    _ = content
    enuminfo = re.match('^EOS_ENUM_(START|END)\\((?P<name>[a-zA-Z_]+)\\);?$', line)
    assert enuminfo
    assert enuminfo['name'] in ('EOS_EResult', 'EOS_UI_EKeyCombination', 'EOS_UI_EInputStateButtonFlags')
    return (i, OrderedDict(
        comment = comment,
        name = enuminfo['name'],
        source = file,
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
        return (i, 'EOS_UI_EKeyCombination', enum_last_index, OrderedDict(
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
        return (i, 'EOS_UI_EInputStateButtonFlags', enum_last_index, OrderedDict(
            comment = comment,
            name = effective_name,
            value = value,
        ))
    assert False

def parse_typedef(content, i, line, comment = '', file = ''):
    """Extract a typedef's content from a list of lines"""
    _ = (content, file)
    definfo = re.match('^(?P<extern>EOS_EXTERN_C )?typedef (?P<type>.+) ((?P<name>[a-zA-Z0-9_]+)|(?P<signature>\\(.*\\* *(?P<name2>[a-zA-Z0-9_]+)\\)\\(.*\\)));$', line)
    assert definfo
    defname = definfo['name'] or definfo['name2'].strip()
    return (i, OrderedDict(
        comment = comment,
        extern = definfo['extern'] is not None,
        name = defname,
        source = file,
        type = definfo['type'].strip() + (
            definfo['signature'].replace(
                defname if f" {defname}" not in definfo['signature'] else f" {defname}", '', 1
            ).replace('(EOS_CALL *', '(*').replace('(EOS_MEMORY_CALL *', '(*') if definfo['signature'] is not None else ''
        ),
    ))

def parse_skip_line(content, i, line, comment = '', file = ''):
    """Parse noop that only returns the received line index"""
    _ = (content, line, comment, file)
    return (i, None)

def build_header_file_index(dir_path):
    """Load the content of all header files in a directory."""
    files_index = {}
    for path, dirs, files in os.walk(dir_path):
        dirs.sort()
        for file in sorted(files):
            assert file not in files_index
            if any(file.endswith(ext) for ext in ('.h', '.inl')):
                with open(os.path.join(path, file), 'r', encoding='utf8') as handle:
                    files_index[file] = handle.readlines()
    return files_index

def build_file_read_order(files_index):
    """From a list of header files, determine in which order they should be parsed."""
    # List includes for each files
    files_priority = OrderedDict()
    for file, content in files_index.items():
        includes = set()
        for line in content:
            if line.startswith('#include '):
                included = re.match('^#include +(?P<path>[^ ]+)$', line)
                assert included
                path = included['path'].strip()
                if path.startswith('"') and path.endswith('"'):
                    if any(file.endswith(ext) for ext in ('.h', '.inl')):
                        assert path[1:-1] in files_index
                        includes.add(path[1:-1])
                elif (path.startswith('<') and path.endswith('>')) or re.match('^[a-zA-Z0-9_]+$', path):
                    pass
                else:
                    assert False
        files_priority[file] = includes

    # Exclude .inl files that are never included in .h files
    excluded_files = []
    for f in files_priority:
        if f.endswith('.inl') and not any(k.endswith('.h') and f in v for k,v in files_priority.items()):
            excluded_files.append(f)
    for f in excluded_files:
        del files_priority[f]

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

def assert_insert(target, value_key, value):
    """Ensure that a value is not already inserted before injecting it"""
    assert value[value_key] not in target
    target[value[value_key]] = value

def assert_insert_if(target, ignores, value_key, value):
    """Ensure that a value should not be ignored and is not already inserted before injecting it"""
    if value[value_key] == 'EOS_AntiCheatClient_ReceiveMessageFromPeer':
        assert False
    if value[value_key] not in ignores:
        assert value[value_key] not in target
        target[value[value_key]] = value

def noop(*args, **kwargs):
    """Just do nothing"""
    return (args, kwargs)

def index_sdk_directory(dir_path): # pylint: disable=too-many-locals
    """
    Parse the Epic Games SDK's library to generate an index of its declarations.
    """
    defines = {}
    functions = {}
    callbacks = {}
    structs = {}
    typedefs = {}
    enums = OrderedDict(
        EOS_EResult = OrderedDict(
            enumname = 'EOS_EResult',
            source = 'eos_common.h',
            values = OrderedDict(),
        ),
        EOS_UI_EKeyCombination = OrderedDict(
            enumname = 'EOS_UI_EKeyCombination',
            source = 'eos_ui_keys.h',
            values = OrderedDict(),
        ),
        EOS_UI_EInputStateButtonFlags = OrderedDict(
            enumname = 'EOS_UI_EInputStateButtonFlags',
            source = 'eos_ui_buttons.h',
            values = OrderedDict(),
        ),
    )

    # Index all headers
    files_index = build_header_file_index(dir_path)
    files_order = build_file_read_order(files_index)
    # Overwride eos_base as it mostly provides hard-to-parse definitions.
    assert 'eos_base.h' in files_order
    files_index['eos_base.h'] = [
        'typedef int32_t EOS_Bool;',
        '#define EOS_TRUE 1',
        '#define EOS_FALSE 0',
    ]

    flags = [
        ('EOS_DECLARE_FUNC', parse_function, partial(assert_insert, functions, 'methodname_flat')),
        ('EOS_DECLARE_CALLBACK', parse_callback, partial(assert_insert, callbacks, 'callbackname')),
        ('EOS_STRUCT', parse_struct, partial(assert_insert, structs, 'struct')),
        ('EOS_RESULT_VALUE', parse_result_value, partial(assert_insert, enums['EOS_EResult']['values'], 'name')),
        (('EOS_ENUM_START', 'EOS_ENUM_END'), parse_enum_start_end, noop),
        ('EOS_ENUM_BOOLEAN_OPERATORS', parse_skip_line, noop),
        ('EOS_ENUM', parse_enum, partial(assert_insert, enums, 'enumname')),
        ('#define', parse_define, partial(assert_insert_if, defines, DEFINES_IGNORE_LIST, 'name')),
        (('typedef', 'EOS_EXTERN_C'), parse_typedef, partial(assert_insert, typedefs, 'name')),
        (DIRECTIVES_IGNORE_LIST, absorb_directive, noop)
    ]
    # Build API index
    for file in files_order:
        content = files_index[file]
        i = 0
        enum_last_index = 0
        last_file_comment = ''
        while i < len(content):
            line = content[i]
            i += 1
            last_file_comment = ''

            if line.lstrip().startswith('/*'):
                while line.lstrip().startswith('/*'):
                    (i, last_file_comment) = absorb_comment(content, i, line)
                    if i >= len(content):
                        i += 1
                        break
                    line = content[i]
                    i += 1
                if i > len(content):
                    continue

            for (linestart, callback, registrar) in flags:
                if any(line.startswith(s) for s in ((linestart,) if isinstance(linestart, str) else linestart)):
                    (i, definition) = callback(content, i, line, last_file_comment, file)
                    registrar(definition)
                    break
            else:
                if line.startswith('EOS_UI_'):
                    (i, parent, enum_last_index, definition) = parse_ui_enum(i, line, last_file_comment, file, enum_last_index)
                    assert definition['name'] not in enums[parent]['values']
                    enums[parent]['values'][definition['name']] = definition

                elif line.lstrip().startswith('//') or line.strip() == '':
                    pass

                else:
                    logger.error("Found unrecognized / unsupported prefix: %s", line)
                    assert False

    return OrderedDict(
        callback_methods = [*callbacks.values()],
        defines = [*defines.values()],
        enums = [sort_dict(OrderedDict(values = [*v.pop('values').values()], **v)) for v in enums.values()],
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
    return OrderedDict(
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

        json_index = OrderedDict()
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
