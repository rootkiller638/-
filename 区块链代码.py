import hashlib
import time
import random
import asyncio
from functools import lru_cache
from typing import Tuple, Dict
from dataclasses import dataclass
from ecdsa import VerifyingKey, SigningKey

# ======================
# 基础数据结构优化
# ======================

@dataclass(frozen=True)
class Transaction:
    """不可变的交易数据结构"""
    sender: bytes    # 发送方公钥
    receiver: bytes  # 接收方地址
    amount: int      # 交易金额
    signature: bytes # 数字签名
    timestamp: float # 时间戳

    def validate(self) -> bool:
        """验证交易签名"""
        try:
            vk = VerifyingKey.from_string(self.sender)
            return vk.verify(self.signature, f"{self.receiver}{self.amount}".encode())
        except Exception as e:
            print(f"交易验证失败: {str(e)}")
            return False

class Block:
    def __init__(self, 
                 index: int, 
                 timestamp: float, 
                 transactions: Tuple[Transaction],  # 使用元组替代列表
                 prev_hash: bytes,  # 使用bytes存储哈希
                 nonce: int = 0):
        # 参数验证
        if index < 0:
            raise ValueError("区块索引必须为非负整数")
        if not isinstance(transactions, tuple):
            raise ValueError("交易必须使用不可变元组")

        self.index = index
        self.timestamp = timestamp
        self.transactions = transactions
        self.prev_hash = prev_hash
        self.nonce = nonce
        self._precomputed = None  # 哈希预计算缓存
        self.hash = self.calculate_hash()

    def calculate_hash(self) -> bytes:
        """带缓存的哈希计算优化"""
        if not self._precomputed:
            # 基础字段哈希预计算
            base_str = f"{self.index}{self.timestamp}{self.prev_hash.hex()}"
            self._precomputed = hashlib.sha256(base_str.encode()).digest()
        
        # 动态字段计算
        dynamic_str = f"{self.nonce}{len(self.transactions)}"
        full_hash = hashlib.sha256(self._precomputed + dynamic_str.encode())
        return full_hash.digest()

    def __repr__(self) -> str:
        return f"Block(index={self.index}, hash={self.hash.hex()[:8]}...)"

# ======================
# 共识算法模块化设计
# ======================

class PoWValidator:
    """工作量证明验证器"""
    def __init__(self, difficulty: int = 4):
        self.difficulty = difficulty
        
    def validate(self, block: Block) -> bool:
        """验证区块哈希是否符合难度要求"""
        return block.hash[:self.difficulty] == b"\x00" * self.difficulty
    
    def mine(self, block: Block) -> Block:
        """批量nonce尝试优化"""
        base_nonce = random.randint(0, 1000000)
        for i in range(1000):  # 批量尝试1000个nonce
            block.nonce = base_nonce + i
            if self.validate(block):
                return block
        return self.mine(block)  # 递归重试

class PoSValidator:
    """权益证明验证器"""
    def __init__(self):
        self.stakes: Dict[bytes, int] = {}  # 验证者地址: 质押金额
        self.stake_dates: Dict[bytes, float] = {}  # 质押时间记录

    def add_stake(self, validator: bytes, amount: int):
        """添加质押（带时间加权）"""
        if amount <= 0:
            raise ValueError("质押金额必须大于0")
        self.stakes[validator] = self.stakes.get(validator, 0) + amount
        self.stake_dates[validator] = time.time()

    def get_weighted_stake(self, validator: bytes) -> float:
        """计算时间加权的质押金额"""
        stake = self.stakes[validator]
        age = time.time() - self.stake_dates[validator]  # 质押时长（秒）
        return stake * (1 + age / 86400)  # 每天增加1倍权重

    def select_validator(self) -> bytes:
        """加权随机选择"""
        total = sum(self.get_weighted_stake(v) for v in self.stakes)
        r = random.uniform(0, total)
        current = 0
        
        for validator in self.stakes:
            current += self.get_weighted_stake(validator)
            if current >= r:
                return validator
        raise RuntimeError("未能选择验证者")

# ======================
# 区块链核心实现
# ======================

class Blockchain:
    def __init__(self):
        self.chain = [self.create_genesis_block()]
        self.pow_validator = PoWValidator()
        self.pos_validator = PoSValidator()
        self.metrics = {
            'block_times': [],
            'tx_counts': []
        }

    def create_genesis_block(self) -> Block:
        """创世区块"""
        return Block(0, time.time(), tuple(), b"\x00"*32)

    @lru_cache(maxsize=128)
    def get_block(self, index: int) -> Block:
        """缓存最近访问的区块"""
        return next(b for b in self.chain if b.index == index)

    async def async_add_block(self, block: Block, consensus: str = "pow"):
        """异步添加区块"""
        start_time = time.time()
        
        # 验证所有交易
        if not all(tx.validate() for tx in block.transactions):
            raise ValueError("包含无效交易")

        # 执行共识机制
        if consensus == "pow":
            block = self.pow_validator.mine(block)
        elif consensus == "pos":
            validator = self.pos_validator.select_validator()
            block.nonce = hash(validator)
        else:
            raise ValueError("不支持的共识机制")

        # 更新区块链
        block.prev_hash = self.chain[-1].hash
        self.chain.append(block)
        
        # 记录指标
        self.metrics['block_times'].append(time.time() - start_time)
        self.metrics['tx_counts'].append(len(block.transactions))

    # ======================
    # 质押管理方法
    # ======================
    def stake(self, validator: bytes, amount: int):
        """质押权益（带溢出检查）"""
        if not isinstance(amount, int) or amount > 2**64:
            raise ValueError("无效的质押金额")
        self.pos_validator.add_stake(validator, amount)

    def get_stake(self, validator: bytes) -> int:
        """查询质押金额"""
        return self.pos_validator.stakes.get(validator, 0)

# ======================
# 测试用例
# ======================

def test_pow_mining():
    """工作量证明压力测试"""
    chain = Blockchain()
    block = Block(1, time.time(), tuple(), chain.chain[0].hash)
    
    start = time.time()
    chain.pow_validator.mine(block)
    print(f"PoW挖矿耗时: {time.time()-start:.2f}s")
    assert chain.pow_validator.validate(block)

def test_pos_selection():
    """权益证明选择测试"""
    pos = PoSValidator()
    validator1 = b"validator_1"
    validator2 = b"validator_2"
    
    pos.add_stake(validator1, 100)
    pos.add_stake(validator2, 200)
    
    # 模拟100次选择
    selections = [pos.select_validator() for _ in range(100)]
    ratio = selections.count(validator2) / 100
    print(f"验证者2选择比例: {ratio:.1%}")  # 应接近66.6%

async def demo_usage():
    """示例使用场景"""
    # 生成测试密钥对
    sk = SigningKey.generate()
    vk = sk.verifying_key
    
    # 创建交易
    tx = Transaction(
        sender=vk.to_string(),
        receiver=b"receiver_address",
        amount=100,
        signature=sk.sign(b"receiver_address100"),
        timestamp=time.time()
    )
    
    # 初始化区块链
    chain = Blockchain()
    
    # 添加PoW区块
    block1 = Block(1, time.time(), (tx,), chain.chain[0].hash)
    await chain.async_add_block(block1, "pow")
    
    # 进行权益质押
    chain.stake(b"validator_1", 1000)
    
    # 添加PoS区块
    block2 = Block(2, time.time(), (tx,), chain.chain[-1].hash)
    await chain.async_add_block(block2, "pos")
    
    # 输出区块链信息
    for blk in chain.chain:
        print(f"区块 {blk.index}: {blk.hash.hex()[:16]}...")
    
    print(f"平均出块时间: {sum(chain.metrics['block_times'])/len(chain.metrics['block_times']):.2f}s")

if __name__ == "__main__":
    # 运行测试
    test_pow_mining()
    test_pos_selection()
    
    # 运行演示
    asyncio.run(demo_usage())