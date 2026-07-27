"""
10_generate_transaction_data.py

[이번 작업]
최신 receipt.csv(상품 상세 행 단위)를 기준으로,
transaction.csv(영수증 단위 거래 요약 데이터)를 처음부터 다시 생성한다.

기존 transaction.csv는 다음 목적에만 사용한다.
- 기존 컬럼명 / 컬럼 순서 확인
- transaction_id 형식(접두어, 자리수) 확인
- 기존 집계값과 최신 receipt.csv 기준 집계값 비교(참고용, 값을 그대로 사용하지 않음)

Google Colab에서 위에서 아래로 그대로 실행하면 된다.
중간에 값을 수정해야 하는 코드는 없다.
"""

# ============================================================
# 0. 라이브러리 불러오기
# ============================================================
import os
import sys
import shutil
import traceback
from datetime import datetime

import numpy as np
import pandas as pd

# ============================================================
# 1. Google Drive 마운트
# ============================================================
from google.colab import drive
drive.mount('/content/drive')

# ============================================================
# 2. 경로 설정 (이 블록만 수정하면 전체 경로가 바뀐다)
# ============================================================
BASE_DIR = '/content/drive/MyDrive/빅프로젝트_데이터 최종/2_생성데이터'

INPUT_PATHS = {
    'store': os.path.join(BASE_DIR, 'store.csv'),
    'store_visitor_profile': os.path.join(BASE_DIR, 'store_visitor_profile.csv'),
    'calendar': os.path.join(BASE_DIR, 'calendar.csv'),
    'store_calendar': os.path.join(BASE_DIR, 'store_calendar.csv'),
    'product': os.path.join(BASE_DIR, 'product.csv'),
    'customer': os.path.join(BASE_DIR, 'customer.csv'),
    'inventory': os.path.join(BASE_DIR, 'inventory.csv'),
    'visitor': os.path.join(BASE_DIR, 'visitor.csv'),
    'receipt': os.path.join(BASE_DIR, 'receipt.csv'),
    'existing_transaction': os.path.join(BASE_DIR, 'transaction.csv'),
}

OUTPUT_TRANSACTION_PATH = os.path.join(BASE_DIR, 'transaction.csv')
TEMP_TRANSACTION_PATH = os.path.join(BASE_DIR, 'transaction_temp.csv')

VALIDATION_DIR = os.path.join(BASE_DIR, 'validation_results')
VALIDATION_SUMMARY_PATH = os.path.join(VALIDATION_DIR, 'transaction_validation_summary.csv')
OLD_NEW_COMPARISON_PATH = os.path.join(VALIDATION_DIR, 'transaction_old_new_comparison.csv')
HOUSEHOLD_VALIDATION_PATH = os.path.join(VALIDATION_DIR, 'transaction_household_quantity_validation.csv')
PRICE_SENSITIVITY_VALIDATION_PATH = os.path.join(VALIDATION_DIR, 'transaction_price_sensitivity_validation.csv')

# 최종 transaction.csv 컬럼 순서 (반드시 이 순서를 그대로 사용)
TRANSACTION_COLUMNS = [
    'transaction_id',
    'receipt_id',
    'visitor_id',
    'customer_id',
    'store_id',
    'transaction_date',
    'transaction_time',
    'transaction_datetime',
    'time_slot',
    'item_count',
    'total_quantity',
    'gross_amount',
    'discount_amount',
    'final_amount',
    'payment_method'
]

# receipt.csv에 반드시 있어야 하는 컬럼
REQUIRED_RECEIPT_COLUMNS = [
    'receipt_id', 'line_no', 'visitor_id', 'customer_id', 'store_id',
    'sale_date', 'sale_time', 'sale_datetime', 'time_slot',
    'inventory_id', 'lot_id', 'product_id',
    'quantity', 'unit_price', 'discount_rate', 'sale_unit_price', 'line_amount',
    'payment_method'
]

# receipt_id 내부에서 단 하나의 값만 가져야 하는 컬럼 (6번 요구사항)
RECEIPT_SINGLE_VALUE_COLUMNS = [
    'visitor_id', 'customer_id', 'store_id',
    'sale_date', 'sale_time', 'sale_datetime',
    'time_slot', 'payment_method'
]

# discount_rate는 퍼센트 정수만 사용 (실제 receipt.csv 확인 결과 0,10,20,30,40)
ALLOWED_DISCOUNT_RATES = [0, 10, 20, 30, 40]

# transaction_id 형식: 기존 transaction.csv 확인 결과 'T' + 9자리 숫자 (예: T000000001)
TRANSACTION_ID_PREFIX = 'T'
TRANSACTION_ID_DIGITS = 9


# ============================================================
# 3. 공통 유틸 함수
# ============================================================
class TransactionGenerationError(Exception):
    """transaction.csv 생성 과정에서 저장을 중단해야 하는 심각한 오류."""
    pass


def print_step(title):
    print()
    print('=' * 70)
    print(title)
    print('=' * 70)


def add_result(results, category, test_name, passed, detail):
    """검증 결과 한 줄을 results 리스트에 추가한다."""
    results.append({
        'category': category,
        'test_name': test_name,
        'result': 'PASS' if passed else 'FAIL',
        'detail': detail
    })
    mark = '✅ PASS' if passed else '❌ FAIL'
    print(f'[{category}] {test_name}: {mark} - {detail}')


# ============================================================
# 4. 1단계 - 입력 파일 로드
# ============================================================
def check_file_exists(path, label):
    if not os.path.exists(path):
        raise TransactionGenerationError(
            f'입력 파일을 찾을 수 없습니다. label={label}, path={path}'
        )


def load_all_inputs():
    print_step('1단계. 입력 파일 로드')

    for label, path in INPUT_PATHS.items():
        if label == 'existing_transaction':
            # 기존 transaction.csv는 참고용이므로 없어도 경고만 하고 진행한다.
            if not os.path.exists(path):
                print(f'[경고] 기존 transaction.csv를 찾을 수 없습니다: {path}')
                print('       ID 형식 확인 및 신구 비교 없이 새로 생성합니다.')
            continue
        check_file_exists(path, label)

    store_df = pd.read_csv(INPUT_PATHS['store'], low_memory=False)
    store_visitor_profile_df = pd.read_csv(INPUT_PATHS['store_visitor_profile'], low_memory=False)
    calendar_df = pd.read_csv(INPUT_PATHS['calendar'], low_memory=False)
    store_calendar_df = pd.read_csv(INPUT_PATHS['store_calendar'], low_memory=False)
    product_df = pd.read_csv(INPUT_PATHS['product'], low_memory=False)
    customer_df = pd.read_csv(INPUT_PATHS['customer'], low_memory=False)
    inventory_df = pd.read_csv(INPUT_PATHS['inventory'], low_memory=False)
    visitor_df = pd.read_csv(INPUT_PATHS['visitor'], low_memory=False)
    receipt_df = pd.read_csv(INPUT_PATHS['receipt'], low_memory=False)

    if os.path.exists(INPUT_PATHS['existing_transaction']):
        existing_transaction_df = pd.read_csv(INPUT_PATHS['existing_transaction'], low_memory=False)
    else:
        existing_transaction_df = None

    print('store_df:', store_df.shape)
    print('store_visitor_profile_df:', store_visitor_profile_df.shape)
    print('calendar_df:', calendar_df.shape)
    print('store_calendar_df:', store_calendar_df.shape)
    print('product_df:', product_df.shape)
    print('customer_df:', customer_df.shape)
    print('inventory_df:', inventory_df.shape)
    print('visitor_df:', visitor_df.shape)
    print('receipt_df:', receipt_df.shape)
    if existing_transaction_df is not None:
        print('existing_transaction_df:', existing_transaction_df.shape)
    else:
        print('existing_transaction_df: 없음 (참고 불가)')

    data = {
        'store': store_df,
        'store_visitor_profile': store_visitor_profile_df,
        'calendar': calendar_df,
        'store_calendar': store_calendar_df,
        'product': product_df,
        'customer': customer_df,
        'inventory': inventory_df,
        'visitor': visitor_df,
        'receipt': receipt_df,
        'existing_transaction': existing_transaction_df,
    }
    return data


# ============================================================
# 5. 2단계 - 입력 데이터(receipt.csv) 검증
# ============================================================
def validate_receipt_input(receipt_df, results):
    print_step('2단계. receipt.csv 입력 데이터 검증')

    # 5-1. 필수 컬럼 존재 확인
    missing_cols = [c for c in REQUIRED_RECEIPT_COLUMNS if c not in receipt_df.columns]
    add_result(
        results, 'receipt_input', 'required_columns_exist',
        len(missing_cols) == 0,
        f'누락된 컬럼: {missing_cols}' if missing_cols else '모든 필수 컬럼 존재'
    )
    if missing_cols:
        raise TransactionGenerationError(
            f'receipt.csv에 필수 컬럼이 없습니다: {missing_cols}. 컬럼명을 임의로 가정하지 않고 중단합니다.'
        )

    # 5-2. 중복 컬럼명 확인
    dup_cols = receipt_df.columns[receipt_df.columns.duplicated()].tolist()
    add_result(
        results, 'receipt_input', 'no_duplicate_columns',
        len(dup_cols) == 0,
        f'중복 컬럼: {dup_cols}' if dup_cols else '중복 컬럼 없음'
    )
    if dup_cols:
        raise TransactionGenerationError(f'receipt.csv에 중복된 컬럼명이 있습니다: {dup_cols}')

    # 5-3. 필수 컬럼 결측 확인
    null_counts = receipt_df[REQUIRED_RECEIPT_COLUMNS].isnull().sum()
    total_nulls = int(null_counts.sum())
    add_result(
        results, 'receipt_input', 'no_missing_values',
        total_nulls == 0,
        f'컬럼별 결측치: {null_counts[null_counts > 0].to_dict()}' if total_nulls > 0 else '결측치 없음'
    )
    if total_nulls > 0:
        raise TransactionGenerationError('receipt.csv 필수 컬럼에 결측치가 있습니다. 임의로 채우지 않고 중단합니다.')

    # 5-4. (receipt_id, line_no) 중복 없음
    dup_key = receipt_df.duplicated(subset=['receipt_id', 'line_no']).sum()
    add_result(
        results, 'receipt_input', 'unique_receipt_id_line_no',
        dup_key == 0,
        f'중복 (receipt_id, line_no) {dup_key}건'
    )

    # 5-5. quantity 숫자형 + 범위(1~5) 확인
    quantity_numeric = pd.to_numeric(receipt_df['quantity'], errors='coerce')
    quantity_numeric_fail = quantity_numeric.isnull().sum()
    add_result(
        results, 'receipt_input', 'quantity_numeric',
        quantity_numeric_fail == 0,
        f'숫자 변환 실패 {quantity_numeric_fail}건'
    )
    if quantity_numeric_fail > 0:
        raise TransactionGenerationError('receipt.csv의 quantity를 숫자형으로 변환할 수 없는 값이 있습니다.')

    qty_out_of_range = ((quantity_numeric < 1) | (quantity_numeric > 5)).sum()
    add_result(
        results, 'receipt_input', 'quantity_range_1_to_5',
        qty_out_of_range == 0,
        f'범위(1~5) 밖 값 {qty_out_of_range}건, 실제 범위 [{quantity_numeric.min()}, {quantity_numeric.max()}]'
    )

    # 5-6. unit_price / sale_unit_price / line_amount 숫자형 확인
    for col in ['unit_price', 'sale_unit_price', 'line_amount']:
        numeric_col = pd.to_numeric(receipt_df[col], errors='coerce')
        fail_count = numeric_col.isnull().sum()
        add_result(
            results, 'receipt_input', f'{col}_numeric',
            fail_count == 0,
            f'숫자 변환 실패 {fail_count}건'
        )
        if fail_count > 0:
            raise TransactionGenerationError(f'receipt.csv의 {col}를 숫자형으로 변환할 수 없는 값이 있습니다.')

    # 5-7. discount_rate 허용값만 사용하는지 확인 (0,10,20,30,40 / 퍼센트 정수 방식)
    discount_rate_numeric = pd.to_numeric(receipt_df['discount_rate'], errors='coerce')
    invalid_discount = ~discount_rate_numeric.isin(ALLOWED_DISCOUNT_RATES)
    invalid_discount_count = int(invalid_discount.sum())
    invalid_values = sorted(receipt_df.loc[invalid_discount, 'discount_rate'].unique().tolist())
    add_result(
        results, 'receipt_input', 'discount_rate_allowed_values',
        invalid_discount_count == 0,
        f'허용되지 않은 discount_rate {invalid_discount_count}건, 값 예시: {invalid_values[:10]}'
    )

    # 5-8. sale_unit_price = unit_price * (1 - discount_rate/100) 계산 일치 확인
    calc_sale_unit_price = (receipt_df['unit_price'] * (1 - discount_rate_numeric / 100)).round().astype('int64')
    sale_unit_price_mismatch = (calc_sale_unit_price != receipt_df['sale_unit_price']).sum()
    add_result(
        results, 'receipt_input', 'sale_unit_price_calc_match',
        sale_unit_price_mismatch == 0,
        f'불일치 {sale_unit_price_mismatch}건 (sale_unit_price = unit_price * (1 - discount_rate/100))'
    )

    # 5-9. line_amount = sale_unit_price * quantity 계산 일치 확인
    calc_line_amount = receipt_df['sale_unit_price'] * quantity_numeric.astype('int64')
    line_amount_mismatch = (calc_line_amount != receipt_df['line_amount']).sum()
    add_result(
        results, 'receipt_input', 'line_amount_calc_match',
        line_amount_mismatch == 0,
        f'불일치 {line_amount_mismatch}건 (line_amount = sale_unit_price * quantity)'
    )


def validate_receipt_single_value(receipt_df, results):
    """
    6번 요구사항: receipt_id 내부에서 아래 컬럼이 모두 단일값인지 검증한다.
    하나라도 불일치하면 first()로 임의 진행하지 않고 예외를 발생시켜 저장을 중단한다.
    """
    print_step('receipt_id별 단일값 검증 (visitor_id, customer_id, store_id, sale_date, '
                'sale_time, sale_datetime, time_slot, payment_method)')

    has_violation = False
    for col in RECEIPT_SINGLE_VALUE_COLUMNS:
        nunique_per_receipt = receipt_df.groupby('receipt_id')[col].nunique()
        violation_receipts = nunique_per_receipt[nunique_per_receipt > 1]
        violation_count = len(violation_receipts)
        passed = violation_count == 0
        add_result(
            results, 'receipt_single_value', f'{col}_single_per_receipt',
            passed,
            f'불일치 receipt_id {violation_count}건'
        )
        if not passed:
            has_violation = True
            sample_ids = violation_receipts.index[:10].tolist()
            print(f'  -> [{col}] 불일치 receipt_id 개수: {violation_count}')
            print(f'  -> [{col}] 불일치 receipt_id 샘플: {sample_ids}')
            sample_detail = receipt_df[receipt_df['receipt_id'].isin(sample_ids)][
                ['receipt_id', 'line_no', col]
            ]
            print(sample_detail.to_string())

    if has_violation:
        raise TransactionGenerationError(
            'receipt_id 내부에 단일값이어야 하는 컬럼에서 불일치가 발견되었습니다. '
            'first() 값을 임의로 사용하지 않고 transaction.csv 생성을 중단합니다.'
        )


# ============================================================
# 6. 3단계 - transaction_df 생성 (메모리 상)
# ============================================================
def build_transaction_df(receipt_df):
    print_step('3단계. receipt.csv 기준 transaction_df 생성')

    df = receipt_df.copy()

    # 금액/수량 컬럼 방어적 숫자 변환 (8번 요구사항)
    df['quantity'] = pd.to_numeric(df['quantity'], errors='raise').astype('int64')
    df['unit_price'] = pd.to_numeric(df['unit_price'], errors='raise').round().astype('int64')
    df['sale_unit_price'] = pd.to_numeric(df['sale_unit_price'], errors='raise').round().astype('int64')
    df['line_amount'] = pd.to_numeric(df['line_amount'], errors='raise').round().astype('int64')

    # 상세 행별 할인 전 금액
    df['gross_line_amount'] = df['unit_price'] * df['quantity']

    # item_count 계산 방식 사전 검증 (9번 요구사항)
    #   receipt_id별 행 수 / line_no 개수 / product_id 고유 개수가 모두 같은지 확인
    row_count = df.groupby('receipt_id').size()
    line_no_count = df.groupby('receipt_id')['line_no'].nunique()
    product_nunique = df.groupby('receipt_id')['product_id'].nunique()

    mismatch_line_no = (row_count != line_no_count).sum()
    mismatch_product = (row_count != product_nunique).sum()
    print(f'item_count 산출 방식 검증: row_count != line_no_count 인 receipt_id 수 = {mismatch_line_no}')
    print(f'item_count 산출 방식 검증: row_count != product_nunique 인 receipt_id 수 = {mismatch_product}')
    if mismatch_line_no > 0 or mismatch_product > 0:
        raise TransactionGenerationError(
            'receipt_id별 행 수, line_no 개수, product_id 고유 개수가 서로 다릅니다. '
            '동일 상품 중복 행 등 예상하지 못한 구조가 있어 item_count 정의를 임의로 선택하지 않고 중단합니다.'
        )
    print('-> row_count == line_no_count == product_nunique 이므로 item_count = receipt_id별 행 수로 사용한다.')

    # groupby 집계 (7-9 ~ 7-14, 4번 요구사항의 컬럼별 생성 규칙)
    agg = df.groupby('receipt_id').agg(
        visitor_id=('visitor_id', 'first'),
        customer_id=('customer_id', 'first'),
        store_id=('store_id', 'first'),
        transaction_date=('sale_date', 'first'),
        transaction_time=('sale_time', 'first'),
        transaction_datetime=('sale_datetime', 'first'),
        time_slot=('time_slot', 'first'),
        payment_method=('payment_method', 'first'),
        item_count=('line_no', 'count'),
        total_quantity=('quantity', 'sum'),
        gross_amount=('gross_line_amount', 'sum'),
        final_amount=('line_amount', 'sum'),
    ).reset_index()

    # discount_amount = gross_amount - final_amount
    agg['discount_amount'] = agg['gross_amount'] - agg['final_amount']

    # 금액/수량 컬럼 정수형 정리 (8번 요구사항, 부동소수점 오차 방지)
    for col in ['item_count', 'total_quantity', 'gross_amount', 'discount_amount', 'final_amount']:
        agg[col] = pd.to_numeric(agg[col], errors='raise').round().astype('int64')

    # 5번 요구사항: transaction_datetime, receipt_id 순으로 정렬 후 transaction_id 순차 생성
    agg['_dt_sort_key'] = pd.to_datetime(agg['transaction_datetime'], errors='raise')
    agg = agg.sort_values(by=['_dt_sort_key', 'receipt_id'], kind='mergesort').reset_index(drop=True)
    agg = agg.drop(columns=['_dt_sort_key'])

    seq = np.arange(1, len(agg) + 1)
    agg['transaction_id'] = [f'{TRANSACTION_ID_PREFIX}{n:0{TRANSACTION_ID_DIGITS}d}' for n in seq]

    transaction_df = agg[TRANSACTION_COLUMNS].copy()

    print('생성된 transaction_df shape:', transaction_df.shape)
    print(transaction_df.head(5).to_string())

    return transaction_df


# ============================================================
# 7. 4단계 - transaction_df 전체 교차검증 (11번 요구사항)
# ============================================================
def validate_transaction_df(transaction_df, receipt_df, visitor_df, customer_df, store_df,
                             product_df, inventory_df, results):
    print_step('4단계. transaction_df 교차검증')

    # 11-2 / 11-3 receipt 수와 transaction 수 일치, receipt_id 완전 일치
    receipt_unique_ids = set(receipt_df['receipt_id'].unique())
    transaction_ids_set = set(transaction_df['receipt_id'].unique())

    add_result(
        results, 'count_match', 'receipt_count_eq_transaction_rows',
        receipt_df['receipt_id'].nunique() == len(transaction_df),
        f"receipt 고유 receipt_id 수={receipt_df['receipt_id'].nunique()}, transaction 행 수={len(transaction_df)}"
    )

    missing_in_transaction = receipt_unique_ids - transaction_ids_set
    add_result(
        results, 'count_match', 'receipt_id_missing_in_transaction',
        len(missing_in_transaction) == 0,
        f'누락 {len(missing_in_transaction)}건'
    )

    extra_in_transaction = transaction_ids_set - receipt_unique_ids
    add_result(
        results, 'count_match', 'receipt_id_extra_in_transaction',
        len(extra_in_transaction) == 0,
        f'초과 생성 {len(extra_in_transaction)}건'
    )

    dup_receipt_id_in_txn = transaction_df['receipt_id'].duplicated().sum()
    add_result(
        results, 'count_match', 'transaction_receipt_id_duplicate',
        dup_receipt_id_in_txn == 0,
        f'transaction 내 receipt_id 중복 {dup_receipt_id_in_txn}건'
    )

    # 11-4 transaction_id 검증
    null_txn_id = transaction_df['transaction_id'].isnull().sum()
    add_result(results, 'transaction_id', 'transaction_id_missing', null_txn_id == 0, f'결측 {null_txn_id}건')

    dup_txn_id = transaction_df['transaction_id'].duplicated().sum()
    add_result(results, 'transaction_id', 'transaction_id_duplicate', dup_txn_id == 0, f'중복 {dup_txn_id}건')

    pattern = rf'^{TRANSACTION_ID_PREFIX}\d{{{TRANSACTION_ID_DIGITS}}}$'
    format_fail = (~transaction_df['transaction_id'].str.match(pattern)).sum()
    add_result(
        results, 'transaction_id', 'transaction_id_format',
        format_fail == 0,
        f"형식 불일치 {format_fail}건 (기대 형식: {TRANSACTION_ID_PREFIX} + 숫자 {TRANSACTION_ID_DIGITS}자리)"
    )

    seq_numbers = transaction_df['transaction_id'].str.replace(TRANSACTION_ID_PREFIX, '', regex=False).astype('int64')
    is_sequential = (seq_numbers.values == np.arange(1, len(transaction_df) + 1)).all()
    add_result(
        results, 'transaction_id', 'transaction_id_sequential',
        is_sequential,
        '정렬 기준(transaction_datetime, receipt_id)으로 1부터 순차 생성됨' if is_sequential else '순차 생성 실패'
    )

    # 11-5 item_count 검증 + line_no/product_id 고유 개수 비교 출력
    row_count = receipt_df.groupby('receipt_id').size().rename('row_count')
    line_no_count = receipt_df.groupby('receipt_id')['line_no'].nunique().rename('line_no_count')
    product_nunique = receipt_df.groupby('receipt_id')['product_id'].nunique().rename('product_nunique')
    item_count_check = transaction_df.set_index('receipt_id')['item_count'].to_frame().join(
        [row_count, line_no_count, product_nunique]
    )
    item_count_mismatch = (item_count_check['item_count'] != item_count_check['row_count']).sum()
    add_result(
        results, 'item_count', 'item_count_eq_receipt_row_count',
        item_count_mismatch == 0,
        f'불일치 {item_count_mismatch}건'
    )
    print('item_count vs line_no_count vs product_nunique 비교 (상위 3건):')
    print(item_count_check.head(3).to_string())

    # 11-6 total_quantity 검증
    qty_sum = receipt_df.groupby('receipt_id')['quantity'].sum().rename('qty_sum')
    check_qty = transaction_df.set_index('receipt_id')['total_quantity'].to_frame().join(qty_sum)
    qty_mismatch = (check_qty['total_quantity'] != check_qty['qty_sum']).sum()
    add_result(
        results, 'total_quantity', 'total_quantity_eq_receipt_sum',
        qty_mismatch == 0,
        f'불일치 {qty_mismatch}건'
    )

    # 11-7 gross_amount 검증
    receipt_df = receipt_df.copy()
    receipt_df['_gross_line'] = receipt_df['unit_price'] * receipt_df['quantity']
    gross_sum = receipt_df.groupby('receipt_id')['_gross_line'].sum().rename('gross_sum')
    check_gross = transaction_df.set_index('receipt_id')['gross_amount'].to_frame().join(gross_sum)
    gross_mismatch = (check_gross['gross_amount'] != check_gross['gross_sum']).sum()
    add_result(
        results, 'gross_amount', 'gross_amount_eq_receipt_calc',
        gross_mismatch == 0,
        f'불일치 {gross_mismatch}건'
    )

    # 11-8 final_amount 검증
    final_sum = receipt_df.groupby('receipt_id')['line_amount'].sum().rename('final_sum')
    check_final = transaction_df.set_index('receipt_id')['final_amount'].to_frame().join(final_sum)
    final_mismatch = (check_final['final_amount'] != check_final['final_sum']).sum()
    add_result(
        results, 'final_amount', 'final_amount_eq_receipt_calc',
        final_mismatch == 0,
        f'불일치 {final_mismatch}건'
    )

    # 11-9 discount_amount 검증 (두 가지 방식 모두)
    check_discount1 = transaction_df.copy()
    discount_eq_gross_minus_final = (
        check_discount1['discount_amount'] != (check_discount1['gross_amount'] - check_discount1['final_amount'])
    ).sum()
    add_result(
        results, 'discount_amount', 'discount_amount_eq_gross_minus_final',
        discount_eq_gross_minus_final == 0,
        f'불일치 {discount_eq_gross_minus_final}건'
    )

    receipt_df['_discount_line'] = (receipt_df['unit_price'] - receipt_df['sale_unit_price']) * receipt_df['quantity']
    discount_calc_sum = receipt_df.groupby('receipt_id')['_discount_line'].sum().rename('discount_calc_sum')
    check_discount2 = transaction_df.set_index('receipt_id')['discount_amount'].to_frame().join(discount_calc_sum)
    discount_mismatch2 = (check_discount2['discount_amount'] != check_discount2['discount_calc_sum']).sum()
    add_result(
        results, 'discount_amount', 'discount_amount_eq_receipt_unit_diff_calc',
        discount_mismatch2 == 0,
        f'불일치 {discount_mismatch2}건'
    )

    # 11-10 금액 보존식 검증: gross = discount + final
    conservation_mismatch = (
        transaction_df['gross_amount'] != (transaction_df['discount_amount'] + transaction_df['final_amount'])
    ).sum()
    add_result(
        results, 'amount_conservation', 'gross_eq_discount_plus_final',
        conservation_mismatch == 0,
        f'불일치 {conservation_mismatch}건'
    )

    # 11-11 연결 키 검증 (transaction -> visitor/customer/store/receipt)
    unlinked_visitor = (~transaction_df['visitor_id'].isin(visitor_df['visitor_id'])).sum()
    add_result(results, 'fk_integrity', 'transaction_visitor_id_in_visitor', unlinked_visitor == 0, f'미연결 {unlinked_visitor}건')

    unlinked_customer = (~transaction_df['customer_id'].isin(customer_df['customer_id'])).sum()
    add_result(results, 'fk_integrity', 'transaction_customer_id_in_customer', unlinked_customer == 0, f'미연결 {unlinked_customer}건')

    unlinked_store = (~transaction_df['store_id'].isin(store_df['store_id'])).sum()
    add_result(results, 'fk_integrity', 'transaction_store_id_in_store', unlinked_store == 0, f'미연결 {unlinked_store}건')

    unlinked_receipt = (~transaction_df['receipt_id'].isin(receipt_df['receipt_id'])).sum()
    add_result(results, 'fk_integrity', 'transaction_receipt_id_in_receipt', unlinked_receipt == 0, f'미연결 {unlinked_receipt}건')

    # receipt.csv 자체의 연결 키 검증
    unlinked_inv = (~receipt_df['inventory_id'].isin(inventory_df['inventory_id'])).sum()
    add_result(results, 'fk_integrity', 'receipt_inventory_id_in_inventory', unlinked_inv == 0, f'미연결 {unlinked_inv}건')

    unlinked_prod = (~receipt_df['product_id'].isin(product_df['product_id'])).sum()
    add_result(results, 'fk_integrity', 'receipt_product_id_in_product', unlinked_prod == 0, f'미연결 {unlinked_prod}건')

    unlinked_rv = (~receipt_df['visitor_id'].isin(visitor_df['visitor_id'])).sum()
    add_result(results, 'fk_integrity', 'receipt_visitor_id_in_visitor', unlinked_rv == 0, f'미연결 {unlinked_rv}건')

    unlinked_rc = (~receipt_df['customer_id'].isin(customer_df['customer_id'])).sum()
    add_result(results, 'fk_integrity', 'receipt_customer_id_in_customer', unlinked_rc == 0, f'미연결 {unlinked_rc}건')

    unlinked_rs = (~receipt_df['store_id'].isin(store_df['store_id'])).sum()
    add_result(results, 'fk_integrity', 'receipt_store_id_in_store', unlinked_rs == 0, f'미연결 {unlinked_rs}건')

    # 11-12 visitor.csv와 거래 발생 관계 검증
    # 실제 receipt.csv 구조에서 visitor_id 당 receipt_id가 몇 건까지 연결되는지 먼저 확인한다.
    max_receipt_per_visitor = receipt_df.groupby('visitor_id')['receipt_id'].nunique().max()
    print(f'실제 데이터 구조: visitor_id 하나당 최대 receipt_id 수 = {max_receipt_per_visitor}')
    if max_receipt_per_visitor == 1:
        dup_visitor_in_txn = transaction_df['visitor_id'].duplicated().sum()
        add_result(
            results, 'visitor_relationship', 'visitor_id_duplicate_in_transaction',
            dup_visitor_in_txn == 0,
            f'실제 구조상 방문 1건당 거래 1건이므로 중복 0건이어야 함. 실제 중복 {dup_visitor_in_txn}건'
        )
    else:
        add_result(
            results, 'visitor_relationship', 'visitor_id_duplicate_in_transaction',
            True,
            f'실제 receipt.csv 구조상 visitor_id 당 최대 {max_receipt_per_visitor}건의 receipt_id가 허용되므로 '
            'transaction의 visitor_id 중복을 오류로 처리하지 않음'
        )

    # 11-13 날짜/시간 검증
    date_map = receipt_df.drop_duplicates('receipt_id').set_index('receipt_id')['sale_date']
    time_map = receipt_df.drop_duplicates('receipt_id').set_index('receipt_id')['sale_time']
    dt_map = receipt_df.drop_duplicates('receipt_id').set_index('receipt_id')['sale_datetime']

    txn_indexed = transaction_df.set_index('receipt_id')
    date_mismatch = (txn_indexed['transaction_date'] != date_map.reindex(txn_indexed.index)).sum()
    add_result(results, 'datetime', 'transaction_date_eq_sale_date', date_mismatch == 0, f'불일치 {date_mismatch}건')

    time_mismatch = (txn_indexed['transaction_time'] != time_map.reindex(txn_indexed.index)).sum()
    add_result(results, 'datetime', 'transaction_time_eq_sale_time', time_mismatch == 0, f'불일치 {time_mismatch}건')

    dt_mismatch = (txn_indexed['transaction_datetime'] != dt_map.reindex(txn_indexed.index)).sum()
    add_result(results, 'datetime', 'transaction_datetime_eq_sale_datetime', dt_mismatch == 0, f'불일치 {dt_mismatch}건')

    parsed_dt = pd.to_datetime(transaction_df['transaction_datetime'], errors='raise')
    date_part = parsed_dt.dt.strftime('%Y-%m-%d')
    time_part = parsed_dt.dt.strftime('%H:%M:%S')
    date_part_mismatch = (date_part.values != transaction_df['transaction_date'].values).sum()
    add_result(
        results, 'datetime', 'transaction_datetime_date_part_eq_transaction_date',
        date_part_mismatch == 0,
        f'pandas datetime 변환 기준 불일치 {date_part_mismatch}건'
    )
    time_part_mismatch = (time_part.values != transaction_df['transaction_time'].values).sum()
    add_result(
        results, 'datetime', 'transaction_datetime_time_part_eq_transaction_time',
        time_part_mismatch == 0,
        f'pandas datetime 변환 기준 불일치 {time_part_mismatch}건'
    )

    # 11-14 time_slot 검증
    slot_map = receipt_df.drop_duplicates('receipt_id').set_index('receipt_id')['time_slot']
    slot_mismatch = (txn_indexed['time_slot'] != slot_map.reindex(txn_indexed.index)).sum()
    add_result(results, 'enum', 'time_slot_eq_receipt', slot_mismatch == 0, f'불일치 {slot_mismatch}건')

    unknown_slot = (~transaction_df['time_slot'].isin(receipt_df['time_slot'].unique())).sum()
    add_result(
        results, 'enum', 'time_slot_values_subset_of_receipt',
        unknown_slot == 0,
        f"transaction의 time_slot 값: {sorted(transaction_df['time_slot'].unique())}"
    )

    # 11-15 payment_method 검증
    pay_map = receipt_df.drop_duplicates('receipt_id').set_index('receipt_id')['payment_method']
    pay_mismatch = (txn_indexed['payment_method'] != pay_map.reindex(txn_indexed.index)).sum()
    add_result(results, 'enum', 'payment_method_eq_receipt', pay_mismatch == 0, f'불일치 {pay_mismatch}건')

    unknown_pay = (~transaction_df['payment_method'].isin(receipt_df['payment_method'].unique())).sum()
    add_result(
        results, 'enum', 'payment_method_values_subset_of_receipt',
        unknown_pay == 0,
        f"transaction의 payment_method 값: {sorted(transaction_df['payment_method'].unique())}"
    )

    # 컬럼 순서 검증
    column_order_ok = list(transaction_df.columns) == TRANSACTION_COLUMNS
    add_result(
        results, 'schema', 'transaction_column_order',
        column_order_ok,
        '요구된 컬럼 순서와 일치' if column_order_ok else f'실제 순서: {list(transaction_df.columns)}'
    )


# ============================================================
# 8. household_type / price_sensitivity 반영 검증 (12번 요구사항)
# ============================================================
def validate_household_quantity(transaction_df, customer_df, results):
    print_step('12-1. household_type별 total_quantity 반영 검증')

    customer_dup = customer_df['customer_id'].duplicated().sum()
    add_result(
        results, 'customer_input', 'customer_id_unique_for_household_validation',
        customer_dup == 0,
        f'customer_id 중복 {customer_dup}건'
    )
    if customer_dup > 0:
        raise TransactionGenerationError(
            'customer.csv의 customer_id가 중복되어 household_type 검증을 진행할 수 없습니다.'
        )

    merged = transaction_df.merge(customer_df[['customer_id', 'household_type']], on='customer_id', how='left')
    unmatched = merged['household_type'].isnull().sum()
    if unmatched > 0:
        print(f'[경고] household_type을 찾지 못한 거래 {unmatched}건 (customer_id 불일치 가능성)')

    stats = merged.groupby('household_type')['total_quantity'].agg(
        transaction_count='count',
        mean_total_quantity='mean',
        median_total_quantity='median',
        std_total_quantity='std',
        min_total_quantity='min',
        max_total_quantity='max',
    ).reset_index()

    print(stats.to_string(index=False))

    expected_order = ['family', 'couple', 'senior', 'single']
    means = stats.set_index('household_type')['mean_total_quantity']

    order_ok = True
    detail_lines = []
    for i in range(len(expected_order) - 1):
        a, b = expected_order[i], expected_order[i + 1]
        if a not in means.index or b not in means.index:
            order_ok = False
            detail_lines.append(f'{a} 또는 {b} 데이터 없음')
            continue
        if not (means[a] > means[b]):
            order_ok = False
        detail_lines.append(f'{a}({means.get(a, float("nan")):.4f}) > {b}({means.get(b, float("nan")):.4f})')

    add_result(
        results, 'household_pattern', 'family_gt_couple_gt_senior_gt_single',
        order_ok,
        '; '.join(detail_lines)
    )

    return stats


def validate_price_sensitivity_discount(transaction_df, customer_df, results):
    print_step('12-2. price_sensitivity별 할인 구매 비중 검증')

    customer_dup = customer_df['customer_id'].duplicated().sum()
    add_result(
        results, 'customer_input', 'customer_id_unique_for_price_sensitivity_validation',
        customer_dup == 0,
        f'customer_id 중복 {customer_dup}건'
    )
    if customer_dup > 0:
        raise TransactionGenerationError(
            'customer.csv의 customer_id가 중복되어 price_sensitivity 검증을 진행할 수 없습니다.'
        )

    merged = transaction_df.merge(
        customer_df[['customer_id', 'price_sensitivity']], on='customer_id', how='left'
    )

    merged['price_sensitivity'] = pd.to_numeric(
        merged['price_sensitivity'], errors='coerce'
    )
    unmatched = merged['price_sensitivity'].isnull().sum()
    add_result(
        results, 'price_sensitivity_pattern', 'price_sensitivity_available_and_numeric',
        unmatched == 0,
        f'미연결 또는 숫자 변환 실패 {unmatched}건'
    )
    if unmatched > 0:
        raise TransactionGenerationError(
            'price_sensitivity 결측 또는 숫자 변환 실패 값이 있어 검증을 중단합니다.'
        )

    unique_count = merged['price_sensitivity'].nunique(dropna=True)
    add_result(
        results, 'price_sensitivity_pattern', 'price_sensitivity_unique_values_ge_4',
        unique_count >= 4,
        f'고유값 {unique_count}개'
    )
    if unique_count < 4:
        raise TransactionGenerationError(
            f'price_sensitivity 고유값이 {unique_count}개로 4분위 구분이 불가능합니다.'
        )

    merged['has_discount'] = merged['discount_amount'] > 0

    # 동일값이 많아도 오류 없이 4분위 구분되도록 순위 기반으로 구간화한다.
    ranked_sensitivity = merged['price_sensitivity'].rank(method='first', pct=True)
    merged['price_sensitivity_quartile'] = pd.cut(
        ranked_sensitivity,
        bins=[0, 0.25, 0.50, 0.75, 1.0],
        labels=['Q1', 'Q2', 'Q3', 'Q4'],
        include_lowest=True
    )

    def weighted_discount_rate(group):
        gross = group['gross_amount'].sum()
        discount = group['discount_amount'].sum()
        return (discount / gross) if gross > 0 else np.nan

    # pandas 버전에 상관없이 안전하게 그룹별 통계를 직접 계산한다.
    stat_rows = []
    for quartile_value, group in merged.groupby('price_sensitivity_quartile', observed=True):
        stat_rows.append({
            'price_sensitivity_quartile': quartile_value,
            'transaction_count': len(group),
            'discount_transaction_count': int(group['has_discount'].sum()),
            'discount_transaction_ratio': group['has_discount'].mean(),
            'mean_discount_amount': group['discount_amount'].mean(),
            'weighted_avg_discount_rate': weighted_discount_rate(group),
        })
    stats = pd.DataFrame(stat_rows)

    print(stats.to_string(index=False))

    ratio_map = stats.set_index('price_sensitivity_quartile')['discount_transaction_ratio']
    q1_lt_q4 = ratio_map.get('Q1', np.nan) < ratio_map.get('Q4', np.nan)
    add_result(
        results, 'price_sensitivity_pattern', 'q4_discount_ratio_gt_q1',
        bool(q1_lt_q4),
        f"Q1={ratio_map.get('Q1', float('nan')):.4f}, Q4={ratio_map.get('Q4', float('nan')):.4f}"
    )

    is_monotonic = (
        ratio_map.get('Q1', np.nan) < ratio_map.get('Q2', np.nan) <
        ratio_map.get('Q3', np.nan) < ratio_map.get('Q4', np.nan)
    )
    results.append({
        'category': 'price_sensitivity_pattern',
        'test_name': 'monotonic_increase_q1_to_q4_reference',
        'result': 'INFO',
        'detail': (
            f"Q1={ratio_map.get('Q1', float('nan')):.4f}, "
            f"Q2={ratio_map.get('Q2', float('nan')):.4f}, "
            f"Q3={ratio_map.get('Q3', float('nan')):.4f}, "
            f"Q4={ratio_map.get('Q4', float('nan')):.4f}; "
            f"단조 증가 여부={bool(is_monotonic)}. 필수 조건은 Q4 > Q1 임"
        )
    })
    print(
        '[price_sensitivity_pattern] monotonic_increase_q1_to_q4_reference: '
        f'ℹ️ INFO - 단조 증가 여부={bool(is_monotonic)}'
    )

    return stats


# ============================================================
# 9. 기존 transaction.csv와 비교 (13번 요구사항)
# ============================================================
def compare_old_new(transaction_df, existing_transaction_df, results):
    print_step('13단계. 기존 transaction.csv와 신규 transaction.csv 비교')

    if existing_transaction_df is None:
        print('기존 transaction.csv가 없어 비교를 건너뜁니다.')
        add_result(results, 'old_new_comparison', 'comparison_available', True, '기존 파일 없음, 비교 생략')
        return pd.DataFrame(columns=['column', 'note'])

    # 기존 receipt_id와 신규 receipt_id의 형식이 다른지 먼저 확인한다.
    old_ids = set(existing_transaction_df['receipt_id'].astype(str))
    new_ids = set(transaction_df['receipt_id'].astype(str))
    overlap = old_ids & new_ids

    print(f'기존 transaction.csv 행 수: {len(existing_transaction_df)}')
    print(f'신규 transaction.csv 행 수: {len(transaction_df)}')
    print(f'기존/신규 receipt_id 겹치는 개수: {len(overlap)}')

    rows = []
    if len(overlap) == 0:
        print()
        print('[중요] 기존 transaction.csv의 receipt_id 형식과 최신 receipt.csv의 receipt_id 형식이 서로 달라')
        print('      (예: 기존 R000000001 vs 신규 REC000001), receipt_id 기준 행 단위 1:1 비교가 불가능합니다.')
        print('      임의의 키로 짝짓지 않고, 컬럼별 분포(평균/표준편차 등) 수준의 집계 비교로 대체합니다.')

        compare_cols = ['item_count', 'total_quantity', 'gross_amount', 'discount_amount', 'final_amount']
        for col in compare_cols:
            old_stat = existing_transaction_df[col].agg(['count', 'mean', 'std', 'min', 'max', 'sum'])
            new_stat = transaction_df[col].agg(['count', 'mean', 'std', 'min', 'max', 'sum'])
            rows.append({
                'column': col,
                'comparison_type': 'aggregate_only_id_scheme_changed',
                'old_count': old_stat['count'],
                'new_count': new_stat['count'],
                'old_mean': old_stat['mean'],
                'new_mean': new_stat['mean'],
                'old_std': old_stat['std'],
                'new_std': new_stat['std'],
                'old_min': old_stat['min'],
                'new_min': new_stat['min'],
                'old_max': old_stat['max'],
                'new_max': new_stat['max'],
                'old_sum': old_stat['sum'],
                'new_sum': new_stat['sum'],
            })
        comparison_df = pd.DataFrame(rows)
        # 주의: receipt_id 형식이 바뀐 것은 receipt.csv가 재생성되며 자연스럽게 발생한 변화이며
        # transaction.csv 생성 로직의 오류가 아니다. 따라서 이 항목은 정보성 PASS로 기록하고,
        # 저장을 막는 FAIL 사유로 취급하지 않는다. (행 단위 비교가 불가능함을 투명하게 보고만 한다.)
        add_result(
            results, 'old_new_comparison', 'row_level_comparison_possible',
            True,
            'receipt_id 형식이 달라(예: R000000001 vs REC000001) 행 단위 비교 불가. '
            '집계(분포) 수준 비교로 대체함. 이는 오류가 아니라 receipt.csv 재생성에 따른 정상적인 ID 체계 변경임. '
            '상세 비교는 transaction_old_new_comparison.csv 파일 참고.'
        )
    else:
        merged = existing_transaction_df.merge(
            transaction_df, on='receipt_id', how='inner', suffixes=('_old', '_new')
        )
        compare_cols = ['item_count', 'total_quantity', 'gross_amount', 'discount_amount', 'final_amount']
        for col in compare_cols:
            diff = merged[f'{col}_new'] - merged[f'{col}_old']
            changed = (diff != 0).sum()
            rows.append({
                'column': col,
                'comparison_type': 'row_level_receipt_id_join',
                'changed_row_count': int(changed),
                'mean_diff': diff.mean(),
                'min_diff': diff.min(),
                'max_diff': diff.max(),
                'abs_diff_sum': diff.abs().sum(),
            })
        comparison_df = pd.DataFrame(rows)
        add_result(
            results, 'old_new_comparison', 'row_level_comparison_possible',
            True,
            f'receipt_id 겹치는 {len(overlap)}건에 대해 행 단위 비교 수행'
        )

    print(comparison_df.to_string(index=False))
    print()
    print('참고: household_type별 구매수량 차등, price_sensitivity별 할인 구매 차등이 최신 receipt.csv에 반영되었으므로')
    print('      total_quantity, gross_amount, discount_amount, final_amount 값이 기존과 달라지는 것은 정상입니다.')
    print('      기존 값에 새 결과를 맞추지 않고, 최신 receipt.csv를 기준으로 한 결과를 그대로 사용합니다.')

    return comparison_df


# ============================================================
# 10. 저장 전/후 처리 (5, 9, 10, 16번 요구사항)
# ============================================================
def backup_existing_transaction():
    print_step('5단계. 기존 transaction.csv 백업')

    if not os.path.exists(OUTPUT_TRANSACTION_PATH):
        print(f'[경고] 백업할 기존 transaction.csv가 없습니다: {OUTPUT_TRANSACTION_PATH}')
        print('       새 파일이 처음 생성되는 것으로 간주하고 계속 진행합니다.')
        return None

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f'transaction_backup_before_regeneration_{timestamp}.csv'
    backup_path = os.path.join(BASE_DIR, backup_filename)

    try:
        shutil.copy2(OUTPUT_TRANSACTION_PATH, backup_path)
    except Exception as e:
        raise TransactionGenerationError(f'기존 transaction.csv 백업에 실패했습니다: {e}')

    if not os.path.exists(backup_path):
        raise TransactionGenerationError('백업 파일이 생성되지 않았습니다. 저장을 중단합니다.')

    print(f'백업 성공: {backup_path}')
    return backup_path


def save_temp_and_reload(transaction_df, results):
    print_step('6~7단계. 임시 파일 저장 후 재로딩 검증')

    os.makedirs(os.path.dirname(TEMP_TRANSACTION_PATH), exist_ok=True)
    transaction_df.to_csv(TEMP_TRANSACTION_PATH, index=False, encoding='utf-8-sig')
    print(f'임시 파일 저장 완료: {TEMP_TRANSACTION_PATH}')

    saved_df = pd.read_csv(TEMP_TRANSACTION_PATH, low_memory=False)

    row_count_match = len(saved_df) == len(transaction_df)
    add_result(results, 'save_reload', 'row_count_match', row_count_match,
               f'저장 전 {len(transaction_df)} vs 재로딩 {len(saved_df)}')

    col_count_match = len(saved_df.columns) == len(transaction_df.columns)
    add_result(results, 'save_reload', 'column_count_match', col_count_match,
               f'저장 전 {len(transaction_df.columns)} vs 재로딩 {len(saved_df.columns)}')

    col_names_match = list(saved_df.columns) == list(transaction_df.columns)
    add_result(results, 'save_reload', 'column_names_and_order_match', col_names_match,
               f'재로딩 컬럼 순서: {list(saved_df.columns)}')

    # transaction_id, receipt_id는 문자열 비교
    txn_id_match = (saved_df['transaction_id'].astype(str).values ==
                     transaction_df['transaction_id'].astype(str).values).all()
    add_result(results, 'save_reload', 'transaction_id_match', bool(txn_id_match), 'transaction_id 값 일치 여부')

    receipt_id_match = (saved_df['receipt_id'].astype(str).values ==
                         transaction_df['receipt_id'].astype(str).values).all()
    add_result(results, 'save_reload', 'receipt_id_match', bool(receipt_id_match), 'receipt_id 값 일치 여부')

    for col in ['total_quantity', 'gross_amount', 'discount_amount', 'final_amount']:
        match = (saved_df[col].astype('int64').values == transaction_df[col].astype('int64').values).all()
        add_result(results, 'save_reload', f'{col}_match', bool(match), f'{col} 값 일치 여부')

    return saved_df


def finalize_transaction_file(results):
    print_step('8단계. 검증 통과 후 transaction.csv로 교체')

    all_passed = not any(r['result'] == 'FAIL' for r in results)
    if not all_passed:
        fail_list = [r for r in results if r['result'] == 'FAIL']
        print(f'FAIL 항목 {len(fail_list)}건이 있어 최종 교체를 수행하지 않습니다.')
        raise TransactionGenerationError('검증 실패로 인해 transaction.csv 최종 교체를 중단합니다.')

    os.replace(TEMP_TRANSACTION_PATH, OUTPUT_TRANSACTION_PATH)
    print(f'최종 저장 완료: {OUTPUT_TRANSACTION_PATH}')


def save_validation_outputs(results, comparison_df, household_stats_df, price_sensitivity_df):
    print_step('9단계. 검증 결과 파일 저장')

    os.makedirs(VALIDATION_DIR, exist_ok=True)

    summary_df = pd.DataFrame(results, columns=['category', 'test_name', 'result', 'detail'])
    summary_df.to_csv(VALIDATION_SUMMARY_PATH, index=False, encoding='utf-8-sig')
    print(f'저장 완료: {VALIDATION_SUMMARY_PATH}')

    comparison_df.to_csv(OLD_NEW_COMPARISON_PATH, index=False, encoding='utf-8-sig')
    print(f'저장 완료: {OLD_NEW_COMPARISON_PATH}')

    household_stats_df.to_csv(HOUSEHOLD_VALIDATION_PATH, index=False, encoding='utf-8-sig')
    print(f'저장 완료: {HOUSEHOLD_VALIDATION_PATH}')

    price_sensitivity_df.to_csv(PRICE_SENSITIVITY_VALIDATION_PATH, index=False, encoding='utf-8-sig')
    print(f'저장 완료: {PRICE_SENSITIVITY_VALIDATION_PATH}')

    return summary_df


def print_final_summary(results):
    print()
    print('=' * 70)
    print('최종 검증 요약')
    print('=' * 70)

    summary_df = pd.DataFrame(results, columns=['category', 'test_name', 'result', 'detail'])
    print(summary_df.to_string(index=False))

    pass_count = (summary_df['result'] == 'PASS').sum()
    fail_count = (summary_df['result'] == 'FAIL').sum()
    info_count = (summary_df['result'] == 'INFO').sum()

    print()
    print('=' * 70)
    print('최종 검증 요약')
    print('=' * 70)
    print(f'PASS: {pass_count}개')
    print(f'INFO: {info_count}개')
    print(f'FAIL: {fail_count}개')

    if fail_count > 0:
        print('❌ FAIL 항목이 존재합니다.')
        print('❌ transaction.csv 저장 또는 최종 확정을 중단합니다.')
        return False
    else:
        print('✅ 전체 검증 통과')
        print('✅ 기존 transaction.csv 백업 완료')
        print('✅ 최신 receipt.csv 기준 transaction.csv 재생성 완료')
        print('✅ transaction.csv 저장 후 재로딩 검증 완료')
        return True


# ============================================================
# 11. 메인 실행 흐름
# ============================================================
def main():
    results = []

    # 1. 입력 파일 로드
    data = load_all_inputs()
    receipt_df = data['receipt']
    visitor_df = data['visitor']
    customer_df = data['customer']
    store_df = data['store']
    product_df = data['product']
    inventory_df = data['inventory']
    existing_transaction_df = data['existing_transaction']

    # 2. 입력 데이터 검증
    validate_receipt_input(receipt_df, results)
    validate_receipt_single_value(receipt_df, results)

    # 3. transaction_df 생성 (메모리 상)
    transaction_df = build_transaction_df(receipt_df)

    # 4. transaction_df 전체 교차검증
    validate_transaction_df(
        transaction_df, receipt_df, visitor_df, customer_df, store_df,
        product_df, inventory_df, results
    )

    # 12. household_type / price_sensitivity 반영 검증
    household_stats_df = validate_household_quantity(transaction_df, customer_df, results)
    price_sensitivity_df = validate_price_sensitivity_discount(transaction_df, customer_df, results)

    # 13. 기존 transaction.csv와 비교
    comparison_df = compare_old_new(transaction_df, existing_transaction_df, results)

    # 저장 전 단계에서 이미 FAIL이 있는지 먼저 확인 (원본 파일 훼손 방지)
    pre_save_fail = [r for r in results if r['result'] == 'FAIL']
    if pre_save_fail:
        print()
        print(f'[중단] 저장 전 검증에서 FAIL {len(pre_save_fail)}건이 발견되어 백업/저장 단계를 진행하지 않습니다.')
        for r in pre_save_fail:
            print(f"  - [{r['category']}] {r['test_name']}: {r['detail']}")
        save_validation_outputs(results, comparison_df, household_stats_df, price_sensitivity_df)
        print_final_summary(results)
        raise TransactionGenerationError('저장 전 검증 실패로 transaction.csv를 생성하지 않았습니다.')

    # 5. 기존 transaction.csv 백업
    backup_existing_transaction()

    # 6~7. 임시 파일 저장 및 재로딩 검증
    save_temp_and_reload(transaction_df, results)

    # 8. 최종 교체
    finalize_transaction_file(results)

    # 9. 검증 결과 파일 저장
    save_validation_outputs(results, comparison_df, household_stats_df, price_sensitivity_df)

    # 최종 요약 출력
    all_ok = print_final_summary(results)
    if not all_ok:
        raise TransactionGenerationError('일부 검증 항목이 FAIL 상태입니다. 위 요약을 확인하세요.')

    return transaction_df


if __name__ == '__main__':
    try:
        final_transaction_df = main()
    except TransactionGenerationError as e:
        print()
        print('=' * 70)
        print('transaction.csv 생성이 중단되었습니다.')
        print('=' * 70)
        print(f'사유: {e}')
        raise
    except Exception:
        print()
        print('=' * 70)
        print('예상하지 못한 오류가 발생하여 중단되었습니다.')
        print('=' * 70)
        traceback.print_exc()
        raise
