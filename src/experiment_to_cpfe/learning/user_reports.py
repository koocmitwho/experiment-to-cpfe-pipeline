"""Readable delivery of checked in-memory predictions; never reopens scientific inputs."""
import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from experiment_to_cpfe.mechanics.tensile import regression_metrics


def _numbers(value, label):
    original = np.asarray(value)
    if original.dtype.kind not in 'ifu':
        raise ValueError(f'{label} must contain real numeric values')
    result = np.asarray(original, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError(f'{label} must contain finite values')
    return result


def _checked(arrays, report, evaluated):
    prediction = _numbers(arrays['prediction'], 'prediction')
    quantities = report['targets']
    if (not isinstance(quantities, list) or not quantities
            or any(not isinstance(q.get(k), str) or not q[k].strip() for q in quantities for k in ('name', 'unit'))
            or len({q['name'] for q in quantities}) != len(quantities)):
        raise ValueError('unique nonempty target names and units are required')
    if prediction.ndim != 2 or not len(prediction) or prediction.shape[1] != len(quantities):
        raise ValueError('prediction must be nonempty with one column per declared target')
    count = len(prediction)
    if report.get('rows', count) != count:
        raise ValueError('report row count differs from predictions')
    for key, expected in (('target_names', [q['name'] for q in quantities]),
                          ('target_units', [q['unit'] for q in quantities])):
        actual = np.asarray(arrays[key])
        if actual.shape != (len(quantities),) or actual.tolist() != expected:
            raise ValueError(f'{key} differ from report declarations')
    identity = {}
    for key in ('sample_ids', 'row_ids', 'groups'):
        value = np.asarray(arrays[key])
        if value.shape != (count,) or any(not isinstance(x, str) or not x.strip() for x in value.tolist()):
            raise ValueError(f'{key} must contain one nonempty string per observation')
        identity[key] = value.tolist()
    if len(set(zip(identity['sample_ids'], identity['row_ids']))) != count:
        raise ValueError('duplicate sample/row identity')
    if not evaluated and 'targets' in arrays:
        raise ValueError('unlabelled delivery cannot receive a truth targets array')
    truth = None
    baseline = None
    if evaluated:
        if 'targets' not in arrays:
            raise ValueError('evaluated delivery requires aligned truth targets')
        truth = _numbers(arrays['targets'], 'truth')
        if truth.shape != prediction.shape:
            raise ValueError('truth width and row count must match predictions')
        means = (report.get('model') or {}).get('normalization', {}).get('y_mean')
        if means is not None:
            baseline = _numbers(means, 'training mean').reshape(-1)
            if baseline.shape != (len(quantities),):
                raise ValueError('training mean width must match targets')
    return prediction, truth, baseline, identity, quantities


def _csv_text(value):
    """Escape text reversibly without relying on spreadsheet quote interpretation."""
    if value and (value[0].isspace() or value[0] in '=+-@\\\''):
        return '\\' + value
    return value


def _markdown(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('\\', '\\\\').replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')
            .replace('`', '\\`'))


def _comparison(model, baseline):
    return {key: 'lower' if model[key] < baseline[key] else 'higher' if model[key] > baseline[key] else 'equal'
            for key in ('rmse', 'mae')}


def _evaluation(prediction, truth, baseline, quantities, report):
    if truth is None:
        return {}, dict(status='not_evaluated', requirements='not_evaluated', limits={})
    metrics = {}
    # Reject numerical overflow before any delivery artifact is written.
    try:
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            for index, q in enumerate(quantities):
                model = regression_metrics(truth[:, index], prediction[:, index])
                base = (regression_metrics(truth[:, index], np.full(len(truth), baseline[index]))
                        if baseline is not None else None)
                metrics[q['name']] = dict(unit=q['unit'], model=model, baseline=base,
                    baseline_comparison=_comparison(model, base) if base else dict(status='unavailable'))
    except FloatingPointError as exc:
        raise ValueError('metric calculation exceeded the finite numeric range') from exc
    purpose = report.get('purpose_evaluation')
    if purpose is not None:
        # The strict evaluator has already applied its frozen purpose policy.
        # Presentation must not reclassify that result with a second policy.
        original = purpose['assessment']
        return metrics, dict(status=original['model'], requirements=original['requirements'],
            limits=purpose['requirements'], source='purpose_evaluation.assessment.model',
            source_assessment=dict(original),
            policy='Present the existing strict purpose-evaluation verdict unchanged; no acceptance policy is recomputed here.')
    limits = ((report.get('evaluation_plan') or {}).get('metrics') or {}).get('rmse_limits') or {}
    checked_limits = {}
    for name, limit in limits.items():
        if name not in metrics:
            raise ValueError('threshold target is absent')
        value = limit.get('value')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value < 0:
            raise ValueError('threshold requires a finite nonnegative value')
        if limit.get('unit') != metrics[name]['unit']:
            raise ValueError('threshold unit differs from target unit')
        if not isinstance(limit.get('basis'), str) or not limit['basis'].strip():
            raise ValueError('threshold requires its prespecified basis')
        checked_limits[name] = dict(value=value, unit=limit['unit'], basis=limit['basis'],
                                    met=metrics[name]['model']['rmse'] <= value)
    requirements = ('failed' if any(not v['met'] for v in checked_limits.values()) else
                    'met' if set(checked_limits) == set(metrics) else 'not_assessed')
    baseline_better = baseline is not None and all(item['baseline_comparison']['rmse'] == 'lower'
                                                   for item in metrics.values())
    if not checked_limits:
        status = 'not_assessed'
    elif requirements == 'failed':
        status = 'failed'
    elif requirements == 'met' and baseline is not None:
        status = 'passed' if baseline_better else 'failed'
    else:
        status = 'not_assessed'
    return metrics, dict(status=status, requirements=requirements, limits=checked_limits,
        policy='A full model acceptance requires all prespecified RMSE limits and lower per-target RMSE than the frozen training mean; no new scientific threshold is invented.')


def _plots(output, prediction, truth, quantities):
    try:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except ImportError as exc:
        return dict(status='unavailable', reason=f'optional matplotlib unavailable: {exc}', files=[])
    files = []
    for index, q in enumerate(quantities):
        figure = Figure(figsize=(7, 4.5), dpi=140, constrained_layout=True)
        canvas = FigureCanvasAgg(figure)
        ax = figure.subplots()
        if truth is not None:
            y, p = truth[:, index], prediction[:, index]
            ax.scatter(y, p, s=14, alpha=.7)
            lower, upper = float(min(y.min(), p.min())), float(max(y.max(), p.max()))
            if lower == upper:
                lower, upper = lower-.5, upper+.5
            ax.plot([lower, upper], [lower, upper], color='black', linestyle='--', linewidth=1)
            ax.set_xlabel(f'Observed ({q["unit"]})', parse_math=False, usetex=False)
        else:
            ax.scatter(np.arange(len(prediction)), prediction[:, index], s=14, alpha=.7)
            ax.set_xlabel('Observation index (saved order)', parse_math=False, usetex=False)
        ax.set_ylabel(f'Predicted ({q["unit"]})', parse_math=False, usetex=False)
        ax.set_title(q['name'], parse_math=False, usetex=False)
        ax.grid(alpha=.2)
        buffer = io.BytesIO()
        canvas.print_png(buffer)
        name = f'target-{index+1:03d}.png'
        with (output/name).open('xb') as stream:
            stream.write(buffer.getvalue())
        files.append(dict(path=name, target=q['name'], unit=q['unit'],
                          kind='observed_vs_predicted' if truth is not None else 'predictions_in_saved_order'))
        figure.clear()
    return dict(status='completed', files=files)


def _number(value):
    return '未定义' if value is None else f'{value:.8g}'


def _source_cells(report, sample_id, row_id, target):
    sources=[source for source in report.get('sources',[]) if source['sample_metadata']['sample_id']==sample_id]
    if len(sources)!=1:
        return ['','','','']
    source=sources[0]
    position=source['row_ids'].index(row_id)
    columns=source['columns']
    selected=columns.get(target,next(iter(columns.values())))
    asset_id=selected['asset_ids'][position]
    assets={a['asset_id']:a for a in source['assets']}
    asset=assets[asset_id]
    while asset.get('parent_asset_id') is not None:
        asset=assets[asset['parent_asset_id']]
    original=source.get('solver_inputs',{}).get('original_source',{})
    filename=original.get('file',asset['uri'])
    if original.get('member'):filename+='!'+original['member']
    records=selected.get('physical_records',[])
    physical=records[position] if records else {}
    return [filename,original.get('sha256',asset.get('sha256') or ''),
            str(physical.get('source_sheet') or ''),str(physical.get('source_row') or '')]


def _summary(delivery, report, csv_name):
    evaluated = delivery['evaluation']
    lines = ['# 预测与评价结果', '',
        '工程交付：本次结果已整理。最终运行状态以同目录的 ' + ('evaluation.json' if evaluated else 'inference.json') + ' 为准。',
        f'观测行：{delivery["rows"]}；样本：{delivery["samples"]}；声明分组：{delivery["groups"]}。', '',
        f'逐行数据：[打开 {csv_name}]({csv_name})；结构化说明：[user-delivery.json](user-delivery.json)。', '']
    assessment = delivery['model_assessment']
    if not evaluated:
        lines.extend(['模型数值：本次为无标签推理，没有读取真值、计算误差或判断精度。', ''])
    else:
        if assessment.get('source') == 'purpose_evaluation.assessment.model':
            lines.extend([f'模型数值：沿用严格用途评价的判定 `{assessment["status"]}`。',
                '判定来源：`purpose_evaluation.assessment.model`；与已有用途报告保持一致，未重新制定判定规则。',
                f'原用途门槛状态：`{assessment["requirements"]}`；'
                f'原基线比较：`{assessment["source_assessment"]["baseline_comparison"]}`。'])
        else:
            verdict = {'passed':'通过已声明的数值要求', 'failed':'未通过已声明的数值要求',
                       'not_assessed':'未设完整标准，不作模型通过判定'}[assessment['status']]
            lines.append(f'模型数值：{verdict}。')
        lines.extend(['',
            '|目标|单位|RMSE|MAE|bias|最大绝对误差|NRMSE|R²|训练均值 RMSE|训练均值 MAE|RMSE/MAE 相对基线|',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|'])
        translated = {'lower':'较低', 'higher':'较高', 'equal':'相同'}
        for name, item in delivery['metrics'].items():
            model, baseline = item['model'], item['baseline']
            comparative = (' / '.join(translated[item['baseline_comparison'][key]] for key in ('rmse','mae'))
                           if baseline else '训练均值未提供')
            values = [_markdown(name), _markdown(item['unit']),
                      *[_number(model[key]) for key in ('rmse','mae','bias','max_abs_error','nrmse','r2')],
                      _number(baseline['rmse']) if baseline else '不可用',
                      _number(baseline['mae']) if baseline else '不可用', comparative]
            lines.append('|'+'|'.join(values)+'|')
        lines.extend(['', '各目标分别计算，不合并不同单位。残差为预测减真值；训练均值来自已冻结模型，未使用本次真值重新拟合。',
                      'R² 可以为负；常数真值时无定义。RMSE/MAE 的基线比较分别报告，较低不等于实验适用性已成立。'])
        for name, limit in assessment['limits'].items():
            lines.append(f'- 预设 RMSE 门槛 {_markdown(name)}：≤ {_number(limit["value"])} {_markdown(limit["unit"])}；'
                         f'{"达到" if limit["met"] else "未达到"}。依据：{_markdown(limit["basis"])}。')
    task = report.get('task_assessment') or {}
    lines.extend(['', f'任务声明状态：{_markdown(task.get("status", "unavailable"))}。',
        '科学边界：这些输出不建立材料物理正确性、独立实验有效性或跨材料泛化能力。分组身份为来源声明，不自动证明物理独立。',
        '本次评价顺序不能证明数据此前从未被观察或用于选模。'])
    gaps = {key:value for key,value in task.items() if key not in ('status',) and value}
    if gaps:
        lines.append('声明与条件详情：'+_markdown(json.dumps(gaps, ensure_ascii=False, allow_nan=False))+'。')
    if delivery['plots']['status'] == 'completed':
        lines.append('')
        for item in delivery['plots']['files']:
            lines.append(f'![{_markdown(item["target"])}]({item["path"]})')
    else:
        lines.extend(['', '图未生成：'+_markdown(delivery['plots']['reason'])+'。数值表和指标已保留。'])
    lines.extend(['', 'CSV 文本编码：backslash-prefix-v1。以公式字符（= + - @）、空白、单引号或反斜杠开头的文本前加一条反斜杠；'
        '读回时，若文本单元格以反斜杠开头，仅去掉第一条即可恢复原值。数字列不作此转义，row_id 保留原 JSON 复合身份文本。', '',
        '下一步：'+('先按样本和原始行核对预测，再在约定时机提供独立真值。' if not evaluated else
        '按目标检查误差和偏差；补齐任务缺项，并在新的独立数据上按预先约定的标准评价。')])
    return '\n'.join(lines)+'\n'


def write_user_delivery(output, arrays, report, *, evaluated=False):
    """Write CSV, Chinese summary and optional plots from already aligned values.

    The returned artifacts use paths relative to ``output``. Scientific inputs,
    checkpoints and paths embedded in ``report`` are never opened. Existing
    delivery files are refused; an existing strict ``REPORT.md`` is untouched.
    """
    prediction, truth, baseline, identities, quantities = _checked(arrays, report, evaluated)
    metrics, assessment = _evaluation(prediction, truth, baseline, quantities, report)
    output = Path(output)
    csv_name = 'evaluation.csv' if evaluated else 'predictions.csv'
    reserved = [csv_name, 'SUMMARY.md', 'user-delivery.json', *[f'target-{i+1:03d}.png' for i in range(len(quantities))]]
    for name in reserved:
        if (output/name).exists():
            raise FileExistsError(f'delivery artifact already exists: {output/name}')
    output.mkdir(parents=True, exist_ok=True)
    headers = ['sample_id', 'row_id', 'group', 'target', 'unit',
               'source_file','source_sha256','source_sheet','source_row',
               'checkpoint_sha256','config_sha256','prediction']
    if evaluated:
        headers += ['truth', 'residual', 'training_mean_baseline']
    with (output/csv_name).open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for row in range(len(prediction)):
            for index, q in enumerate(quantities):
                text = [identities[key][row] for key in ('sample_ids', 'row_ids', 'groups')]+[q['name'], q['unit']]
                source=_source_cells(report,identities['sample_ids'][row],identities['row_ids'][row],q['name'])
                source += [(report.get('model') or {}).get('sha256',''),(report.get('config') or {}).get('sha256','')]
                values = [_csv_text(value) for value in text+source]+[float(prediction[row,index])]
                if evaluated:
                    values += [float(truth[row,index]), float(prediction[row,index]-truth[row,index]),
                               float(baseline[index]) if baseline is not None else '']
                writer.writerow(values)
    plotting = _plots(output, prediction, truth, quantities)
    delivery = dict(format='experiment-to-cpfe-user-delivery-1', engineering='exports_completed', evaluation=evaluated,
        rows=len(prediction), samples=len(set(identities['sample_ids'])), groups=len(set(identities['groups'])),
        targets=quantities, metrics=metrics, model_assessment=assessment,
        csv_text_encoding=dict(name='backslash-prefix-v1', columns=headers[:11],
            encode='Prefix one backslash when the first character is whitespace, = + - @, apostrophe, or backslash.',
            decode='For text columns only: remove exactly one leading backslash if present; otherwise preserve the cell.'),
        plots=plotting)
    with (output/'user-delivery.json').open('x', encoding='utf-8') as stream:
        json.dump(delivery, stream, indent=2, ensure_ascii=False, allow_nan=False)
    with (output/'SUMMARY.md').open('x', encoding='utf-8') as stream:
        stream.write(_summary(delivery, report, csv_name))
    artifacts = {}
    for name in [csv_name, 'SUMMARY.md', 'user-delivery.json', *[item['path'] for item in plotting['files']]]:
        data = (output/name).read_bytes()
        artifacts[name] = dict(path=name, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
    return artifacts
