"""Conservative static rules. No imports/evaluation of inspected source or broker access."""
import ast
import hashlib
import re
from fnmatch import fnmatch
from pathlib import PurePosixPath
from .models import finding


def matches(path, patterns):
    return any(fnmatch(path, p) for p in patterns)


def words(node):
    return ast.unparse(node) if node is not None else ''


def constants(node):
    return [n.value for n in walk_scope(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)] if node is not None else []


def walk_scope(node):
    """Inspect one function without attributing nested routes/functions to their parent."""
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from walk_scope(child)


def calls(node):
    return [n for n in walk_scope(node) if isinstance(n, ast.Call)]


def tail(node):
    return words(node.func).split('.')[-1]


def functions(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def write_call(call):
    return tail(call) in ('save', 'write_text', 'write_bytes', 'dump', 'replace', 'copy', 'copy2', 'update', 'setdefault') or tail(call) == 'open' and any(isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in ('w', 'a', 'wb', 'ab') for n in call.args)


def guarded(fn, name):
    # An aborting negative guard before a later submission in this function.
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not) and any(tail(c) == name for c in calls(n.test)):
            if any(isinstance(x, (ast.Raise, ast.Return)) for statement in n.body for x in ast.walk(statement)):
                yield n.lineno


def inspect_file(path, raw, policy):
    rows = []
    def add(rule, line=1, anchor='file', detail=None):
        rows.append(finding(policy, rule, path, line, anchor, detail))
    name = PurePosixPath(path).name
    sensitive = policy['sensitive_patterns']
    if (name == '.env' or name.startswith('.env.') and name != '.env.example' or
        any(name.lower().endswith(x) for x in sensitive['extensions']) or name in sensitive['names'] or '-firebase-adminsdk-' in name):
        add('SECURITY-002')
    if raw is None:
        return rows, None
    text = raw.decode('utf-8-sig')
    is_test = matches(path, policy['test_paths'])
    for pattern in sensitive['tokens']:
        for m in re.finditer(pattern, text):
            add('SECURITY-001', text[:m.start()].count('\n')+1, hashlib.sha256(m.group().encode()).hexdigest())
    # Literal secret assignments, including JSON fields and dotenv values; placeholders are explicit.
    key_pattern = r'[\"\']?([A-Za-z_][A-Za-z0-9_-]*)[\"\']?\s*[:=]\s*[\"\']([^\"\'\n]{8,})[\"\']'
    for m in re.finditer(key_pattern, text):
        key, value = m.groups()
        explicit_test_identity = is_test and value == 'A'+'123456789'
        if re.search(sensitive['key_names'], key) and not explicit_test_identity and not re.fullmatch(sensitive['placeholder'], value) and (len(value) >= 20 or re.fullmatch(r'[A-Z][12][0-9]{8}', value)):
            add('SECURITY-001', text[:m.start()].count('\n')+1, key + ':' + hashlib.sha256(value.encode()).hexdigest())
    if name.startswith('.env') or name.endswith('.env.example'):
        for line,value in enumerate(text.splitlines(),1):
            m=re.fullmatch(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\s\"\'#]{20,})\s*(?:#.*)?',value)
            if m and re.search(sensitive['key_names'],m[1]) and not re.fullmatch(sensitive['placeholder'],m[2]):
                add('SECURITY-001',line,m[1]+':'+hashlib.sha256(m[2].encode()).hexdigest())
    logical = path.removeprefix('vm_runtime/')
    public = matches(logical, policy['public_paths'])
    if public:
        for m in re.finditer(policy['public_exposure_rules']['private_infrastructure'], text):
            add('SECURITY-004', text[:m.start()].count('\n')+1, 'private-infrastructure')
        for field in policy['public_exposure_rules']['sensitive_fields']:
            if re.search(r'[\"\']?' + field + r'[\"\']?\s*:', text):
                add('SECURITY-003', 1, 'public-field:'+field)
    if is_test or logical.startswith('guardian/'):
        return rows, None
    if PurePosixPath(path).suffix != '.py':
        if PurePosixPath(path).suffix in ('.sh', '.service', '.yaml', '.yml', '.example', '.js', '.cjs', '.ts') or name.startswith(('Dockerfile', '.env')):
            if re.search(r'LIVE_ORDERING_ENABLED[\"\']?\s*(?:=|:|\|\||\?\?)\s*[\"\']?(?:true|1|yes)\b|LIVE_ORDERING_ENABLED:-true', text, re.I):
                add('TRADING-007')
        if public and re.search(r'(?:import|require).*?(?:order_service|shioaji|live_console)', text):
            add('SECURITY-003', anchor='public-private-dependency')
        if logical.startswith(('deploy/', 'ops/')):
            dangerous_commands(text, add, image_build=name.startswith('Dockerfile'))
        return rows, None
    tree = ast.parse(text, filename=path)
    module_literals={n.targets[0].id:n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)}
    def resolved_strings(node):
        return set(constants(node)) | {module_literals[n.id] for n in ast.walk(node) if isinstance(n,ast.Name) and n.id in module_literals}
    research = matches(logical, policy['research_paths'])
    paper = matches(logical, policy['paper_paths'])
    live = logical in policy['live_paths']
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((a.name, node.lineno) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if node.level:
                parts = logical[:-3].split('/')[:-node.level]
                module = '.'.join(parts + ([module] if module else []))
            imports.append((module, node.lineno))
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = words(node.targets[0] if isinstance(node, ast.Assign) else node.target)
            if '.positions' in target and any(x in words(node.value).lower() for x in ('local', 'ledger')):
                add('TRADING-006', node.lineno, target)
            value = node.value
            if ('LIVE_ORDERING_ENABLED' in constants(node) or target=='LIVE_ORDERING_ENABLED') and isinstance(value, ast.Constant) and str(value.value).lower() in ('true','1','yes'):
                add('TRADING-007', node.lineno, 'literal-enable')
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == 'LIVE_ORDERING_ENABLED' and isinstance(value, ast.Constant) and str(value.value).lower() in ('true','1','yes'):
                    add('TRADING-007', node.lineno, 'dict-enable')
        if isinstance(node, ast.Call) and tail(node) in ('get','getenv','setdefault') and node.args and any(s == 'LIVE_ORDERING_ENABLED' for s in constants(node.args[0])):
            if len(node.args)>1 and isinstance(node.args[1], ast.Constant) and str(node.args[1].value).lower() in ('true','1','yes'):
                add('TRADING-007', node.lineno, 'default-enable')
    if research:
        for module, line in imports:
            if any(module == p or module.startswith(p+'.') for p in policy['forbidden_dependencies']['research']):
                add('TRADING-001', line, 'execution-import:'+module)
    if public:
        for module, line in imports:
            if any(module == p or module.startswith(p+'.') for p in policy['forbidden_dependencies']['public']):
                add('SECURITY-003', line, 'private-import:'+module)
    for fn in functions(tree):
        all_calls = calls(fn)
        fn_text = words(fn)
        # Lexical import bindings, not another route's aliases. Unknown shadowing
        # is never allowed to acquire a Paper exemption.
        fn_aliases={}
        for n in [*tree.body,*walk_scope(fn)]:
            if isinstance(n,ast.Import):fn_aliases.update({a.asname or a.name.split('.')[0]:a.name for a in n.names})
            if isinstance(n,ast.ImportFrom):fn_aliases.update({a.asname or a.name:(n.module or '')+'.'+a.name for a in n.names})
            if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and tail(n.value)=='import_module' and n.value.args and isinstance(n.value.args[0],ast.Constant) and isinstance(n.value.args[0].value,str):
                fn_aliases.update({t.id:n.value.args[0].value for t in n.targets if isinstance(t,ast.Name)})
        for arg in [*fn.args.posonlyargs,*fn.args.args,*fn.args.kwonlyargs]:fn_aliases.pop(arg.arg,None)
        def is_execution(call):
            name=words(call.func);first,*rest=name.split('.')
            resolved=fn_aliases.get(first,first)+('.'+'.'.join(rest) if rest else '')
            operation=resolved.split('.')[-1]
            if operation in ('place_order','submit_order'):return True
            if operation not in ('buy','sell'):return False
            return not any(resolved.startswith(m+'.') for m in ('paper_account','paper_ledger','vm_runtime.paper_account','vm_runtime.paper_ledger'))
        execution = [c for c in all_calls if is_execution(c)]
        if research and execution:
            add('TRADING-001', execution[0].lineno, fn.name+':execution')
        if paper and execution:
            add('TRADING-002', execution[0].lineno, fn.name+':execution')
        for c in all_calls:
            literals = ' '.join(constants(c))
            if tail(c) in ('execute','executemany'):
                if paper and re.search(r'(?:INSERT|UPDATE|DELETE).*live_trade_', literals, re.I):
                    add('TRADING-002', c.lineno, fn.name+':live-ledger-write')
                if (live or logical.endswith('/web.py') and ('live' in fn.name or fn.name == 'post_order_place')) and re.search(r'(?:INSERT|UPDATE|DELETE).*paper_trade_fills', literals, re.I):
                    add('TRADING-002', c.lineno, fn.name+':paper-fill-write')
            if tail(c) in ('set_positions','replace_positions','write_positions') and any(x in words(c).lower() for x in ('local','ledger')):
                add('TRADING-006', c.lineno, fn.name+':broker-overwrite')
        if execution and not research and not paper:
            guard_lines = list(guarded(fn, 'live_ordering_enabled'))
            if any(not any(line<c.lineno for line in guard_lines) for c in execution):
                add('TRADING-003', execution[0].lineno, fn.name+':unguarded-submit')
            low_level = logical == policy['live_guards']['low_level_executor'] and fn.name == 'place_order'
            if not low_level and not ('client_order_id' in fn_text and any(tail(c)=='reserve_order' for c in all_calls)):
                add('TRADING-005', execution[0].lineno, fn.name+':missing-reservation')
        if fn.name == 'live_ordering_enabled':
            returns = [n.value for n in ast.walk(fn) if isinstance(n, ast.Return)]
            expected = policy['live_guards']
            good = any(isinstance(r,ast.BoolOp) and isinstance(r.op,ast.And) and not any(isinstance(n,ast.BoolOp) and isinstance(n.op,ast.Or) for n in ast.walk(r)) and
                       any(isinstance(n,ast.Compare) and expected['enabled'] in resolved_strings(n) for n in ast.walk(r)) and
                       any(isinstance(n,ast.Compare) and any(isinstance(op,ast.Eq) for op in n.ops) and {expected['confirmation'],expected['value']} <= resolved_strings(n) for n in ast.walk(r)) for r in returns)
            if logical == policy['live_guards']['low_level_executor'] and not good:
                add('TRADING-003', fn.lineno, 'dual-guard-structure')
        for branch in (n for n in ast.walk(fn) if isinstance(n, ast.If) and 'kill' in words(n.test).lower()):
            if any(tail(c) in ('flatten','flatten_all','close_all','place_order','submit_order','sell') for statement in branch.body for c in calls(statement)):
                add('TRADING-004', branch.lineno, fn.name+':kill-liquidation')
        if logical == 'easystock_admin/live_console.py' and fn.name == 'state':
            if not any(isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not) and words(n.operand)=='kill' for n in ast.walk(fn)):
                add('TRADING-004', fn.lineno, 'kill-not-blocking')
        # Local, monotonic taint propagation. Read operations are never performed by Guardian.
        tainted_holdout, approved, future = set(), set(), set()
        features = 'feature' in fn.name.lower() or any(x in PurePosixPath(logical).stem.lower() for x in ('feature','context','replay','backfill'))
        label_fn = any(x in fn.name.lower() for x in ('label','outcome','simulate','markout'))
        for n in sorted(walk_scope(fn), key=lambda n:getattr(n,'lineno',0)):
            txt = words(n) if isinstance(n, (ast.Assign,ast.AnnAssign,ast.Call)) else ''
            if isinstance(n, (ast.Assign,ast.AnnAssign)):
                targets = [words(t) for t in n.targets] if isinstance(n,ast.Assign) else [words(n.target)]
                rhs = words(n.value)
                if any(dataset in rhs for dataset in policy['holdout_protections']['datasets']) or any(re.search(r'\b'+re.escape(v)+r'\b',rhs) for v in tainted_holdout):
                    tainted_holdout.update(targets)
                if 'latest-approved.json' in rhs or any(re.search(r'\b'+re.escape(v)+r'\b',rhs) for v in approved):approved.update(targets)
                if re.search(r'\.shift\(-[1-9]|future_close|future_label',rhs):future.update(targets)
                if features and not label_fn and re.search(r'future_close|future_label',rhs):
                    add('RESEARCH-002',n.lineno,fn.name+':future-feature-read')
            if isinstance(n, ast.Call):
                if (tail(n) in ('set_mode','enable_live_auto') and 'LIVE AUTO' in constants(n) or tail(n) in ('execute','executemany') and re.search(r'UPDATE.*live_console_state.*LIVE AUTO',' '.join(constants(n)),re.I)) and 'activation_allowed' not in fn_text:
                    add('TRADING-003',n.lineno,fn.name+':activation-bypass')
                if tail(n) in policy['holdout_protections']['optimization_calls'] and any(re.search(r'\b'+re.escape(v)+r'\b',txt) for v in tainted_holdout):
                    add('RESEARCH-001', n.lineno, fn.name+':holdout-consumption')
                if features and not label_fn and (tail(n)=='shift' and n.args and isinstance(n.args[0],ast.UnaryOp) and isinstance(n.args[0].op,ast.USub) or any(k.arg=='direction' and isinstance(k.value,ast.Constant) and k.value.value in ('forward','nearest') for k in n.keywords) or any(k.arg=='center' and isinstance(k.value,ast.Constant) and k.value.value is True for k in n.keywords)):
                    add('RESEARCH-002',n.lineno,fn.name+':lookahead-operation')
                if tail(n) in ('fit','train','train_candidate') and future and any(re.search(r'\b'+re.escape(v)+r'\b',txt) for v in future):
                    add('RESEARCH-002',n.lineno,fn.name+':future-feature-training')
                if write_call(n) and ('latest-approved.json' in txt or any(re.search(r'\b'+re.escape(v)+r'\b',txt) for v in approved)):
                    gated = logical in policy['promotion_paths'] and 'promotion_gate' in fn_text and ('passed' in fn_text or 'blocked' in fn_text)
                    if not gated:add('RESEARCH-004',n.lineno,fn.name+':approved-write')
                if research and write_call(n) and any(p in txt for p in ('strategy_engine.py','strategy_rules.py','market_risk.py','LIVE_ORDERING_ENABLED','MARKET_RISK_THRESHOLD')):
                    add('RESEARCH-005',n.lineno,fn.name+':production-write')
        if research and any(tail(c) in ('fit','train','train_candidate') for c in all_calls) and ('profile_hash' in fn_text or 'mixed_profiles' in fn_text or re.search(r'concat\(.*profile',fn_text,re.S)):
            if not any(isinstance(n,ast.Compare) and any(isinstance(op,(ast.Eq,ast.NotEq)) for op in n.ops) and 'profile' in words(n) for n in walk_scope(fn)):
                add('RESEARCH-003',fn.lineno,fn.name+':profile-filter')
    if logical.startswith(('ops/','deploy/')):
        dangerous_commands(text, add)
    return rows, (tree, imports)


def dangerous_commands(text, add, image_build=False):
    for line, value in enumerate(text.splitlines(),1):
        if re.search(r'git\s+reset\s+--hard|git\s+clean\s+-[A-Za-z]*f[A-Za-z]*d|rm\s+-[A-Za-z]*r[A-Za-z]*f',value):
            # A literal scratch target or explicit temporary-directory creation is evidence of scope,
            # not carte blanche to delete production paths. Ambiguous variables still need review.
            bounded = re.search(r'rm\s+-rf\s+[\"\']?/tmp/[A-Za-z0-9_-]+',value) and not re.search(r'\.\.|\*|\$|`',value)
            # Docker package-cache cleanup is confined to the image, not the host.
            bounded = bounded or image_build and re.search(r'rm -rf /var/lib/apt/lists/\*(?:\s|$)',value)
            # Recognize this canonical retention guard only, not arbitrary variable targets.
            bounded = bounded or ('"$SNAPSHOT_ROOT_REAL"/*) rm -rf -- "$old_dir_real"' in value and
                'old_dir_real="$(realpath "$old_dir")"' in text and '-mindepth 1 -maxdepth 1' in text and
                'refusing to prune outside snapshot root' in text)
            if not bounded:add('DEPLOY-002',line,'destructive-command')
        if re.search(r'(?:cp|mv|rsync).*?(?:state\.sqlite|easystock-learning-data|credentials|/cert/)',value) and not ('backup' in value or 'mode=ro' in value):
            add('DEPLOY-003',line,'protected-data-destination')


def architecture(files, parsed, manifest, policy, scope=None):
    out=[]
    required=manifest['byte_equivalent']
    for rel in required:
        mirror='vm_runtime/'+rel
        if scope is not None and rel not in scope and mirror not in scope:continue
        if rel not in files or mirror not in files or files[rel] != files[mirror]:
            out.append(finding(policy,'ARCH-002',rel,1,'mirror-pair',other=(mirror,1)))
    classified={*required,*manifest['allowed_different'],*manifest['runtime_only']}
    for path in files:
        if path.startswith('vm_runtime/') and path[11:] not in classified and (scope is None or path in scope):
            out.append(finding(policy,'ARCH-002',path,1,'unclassified-runtime'))
    duplicates={};graph={}
    for path,(tree,imports) in parsed.items():
        module=path[:-3].replace('/','.')
        # Deferred imports do not create module-initialization cycles. Forbidden
        # dependencies above still inspect imports in every scope.
        graph[module]={n.module for n in tree.body if isinstance(n,ast.ImportFrom) and not n.level}
        graph[module].update(a.name for n in tree.body if isinstance(n,ast.Import) for a in n.names)
        for fn in functions(tree):
            responsibility=next((r for r in policy['canonical_responsibilities'] if r in fn.name.lower()),None)
            if not responsibility or len(list(ast.walk(fn)))<12:continue
            shape=ast.dump(ast.Module(body=fn.body,type_ignores=[]),include_attributes=False)
            key=(responsibility,hashlib.sha256(shape.encode()).hexdigest())
            if key in duplicates and duplicates[key][0] != path:
                prior=duplicates[key]
                manifested_pair=path.removeprefix('vm_runtime/')==prior[0].removeprefix('vm_runtime/') and path.removeprefix('vm_runtime/') in required
                if not manifested_pair:out.append(finding(policy,'ARCH-001',path,fn.lineno,fn.name+':duplicate',other=prior))
            else:duplicates[key]=(path,fn.lineno)
    # Tarjan SCC; only imports between tracked modules, with no source import execution.
    index=0;stack=[];indices={};low={};on=set()
    def visit(v):
        nonlocal index
        indices[v]=low[v]=index;index+=1;stack.append(v);on.add(v)
        for w in sorted(graph[v] & graph.keys()):
            if w not in indices:visit(w);low[v]=min(low[v],low[w])
            elif w in on:low[v]=min(low[v],indices[w])
        if low[v]==indices[v]:
            group=[]
            while True:
                w=stack.pop();on.remove(w);group.append(w)
                if w==v:break
            if len(group)>1:
                members=sorted(group);p=members[0].replace('.','/')+'.py'
                out.append(finding(policy,'ARCH-003',p,1,':'.join(members),other=(members[1].replace('.','/')+'.py',1)))
    for v in sorted(graph):
        if v not in indices:visit(v)
    canonical=policy['canonical_deploy']
    if canonical in files and (scope is None or canonical in scope):
        text=files[canonical].decode('utf-8-sig')
        if not all(marker in text for marker in ('is-active','diff --quiet','merge --ff-only','backup','sqlite3.connect')):
            out.append(finding(policy,'DEPLOY-001',canonical,1,'canonical-preservation'))
    return out
