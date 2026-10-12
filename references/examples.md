# Doxygen 注释 — 完整示例与边界情况

所有示例均为 **UTF-8 无 BOM**、4 空格缩进、CRLF 换行。示例日期 `20260921` 为占位，实际替换成当天日期。

---

## 1. 文件头 + 头文件保护（放置位置）

`@file` 块必须在 `#ifndef` / `#pragma once` **之前**，块后留一个空行。

```c
/**
 * @file        frame_decoder.h
 * @brief       IEC 60870-5-104 帧解码接口
 * @author      Your Name
 * @version     1.0
 * @date        20260921
 * @warning     none
 * @note        仅处理 APDU，不含 TCP 链路管理
 *
 * @copyright   Copyright (c) 2026 by Your Company, All Rights Reserved.
 *
 * @par         修改日志:
 * <table>
 * <tr><th>Date        <th>Version   <th>Author    <th>Description
 * <tr><td>20260921    <td>1.0       <td>Your Name <td>新建
 * </table>
 */

#ifndef FRAME_DECODER_H
#define FRAME_DECODER_H

#include <cstdint>
#include <cstddef>

#endif // FRAME_DECODER_H
```

**追加修改日志**（不要覆盖历史行）：

```c
 * <tr><td>20260921    <td>1.0       <td>Your Name <td>新建
 * <tr><td>20261005    <td>1.1       <td>Your Name <td>增加 S 帧计数校验
 * </table>
```

同时把 `@version` 改成 `1.1`、`@date` 改成 `20261005`。

---

## 2. 函数注释：修改前 / 修改后

**修改前**

```c
int decode_apdu(const uint8_t* buf, int len, ApduFrame* out, bool* isIFrame);
```

**修改后**

```c
/**
 * @brief       解析一个 APDU 帧
 *
 * @param[in]   {const uint8_t*} buf 原始字节流
 * @param[in]   {int} len buf 长度（字节）
 * @param[out]  {ApduFrame*} out 解析结果，内部缓冲区由调用方释放
 * @param[out]  {bool*} isIFrame 是否为 I 帧
 * @return      成功返回已消费字节数，失败返回 -1
 *        -     长度不足时返回 -2
 * @retval      0 帧结构合法但无有效数据
 * @todo        none
 * @details     不校验链路层地址域，由上层调用者负责。
 */
int decode_apdu(const uint8_t* buf, int len, ApduFrame* out, bool* isIFrame);
```

要点：
- `buf`、`len` 只读 → `@param[in]`；`out`、`isIFrame` 由函数写出 → `@param[out]`。
- `@return` 一句话总述，`-` 续行补例外情况。
- 无待办也要显式写 `@todo none`。

---

## 3. 无参数无返回值：多余的 `@param` 行整行删除

**修改前**

```c
void reset_link();
```

**修改后**

```c
/**
 * @brief       复位链路状态机
 *
 * @return      none
 * @todo        none
 * @details     清空发送队列与未确认计数，不关闭 TCP 连接。
 */
void reset_link();
```

若函数一目了然，可改用 `doxygen_nom` 短注释：

```c
/**
 * @brief       返回当前链路是否已建立
 *
 */
bool isLinkUp() const;
```

---

## 4. 双向参数：`@param[in,out]`

模板只给了 `in` / `out`，读写参数按下面的形式扩展。

**修改前**

```c
void skipHeader(const uint8_t* buf, size_t* offset);
```

**修改后**

```c
/**
 * @brief       跳过帧头并推进解析游标
 *
 * @param[in]   {const uint8_t*} buf 帧缓冲区
 * @param[in,out] {size_t*} offset 入参为当前偏移，出参为帧头之后的偏移
 * @return      none
 * @todo        none
 * @details     越界时 offset 保持原值不变。
 */
void skipHeader(const uint8_t* buf, size_t* offset);
```

---

## 5. 枚举返回值：`@retval` 的用法

```c
/**
 * @brief       校验单个字节的起始标志
 *
 * @param[in]   {uint8_t} byte 待校验字节
 * @return      校验结果码
 * @retval      CHK_OK 字节合法
 * @retval      CHK_BAD_START 起始字节不是 0x68
 * @todo        none
 * @details     none
 */
CheckResult checkStartByte(uint8_t byte);
```

`@retval` 每个取值写一行；返回值是普通整型时删掉全部 `@retval` 行。

---

## 6. 模块分组：头尾成对包住一组 API

```c
/**
 * @defgroup iec104_apci APCI 层
 *
 * APCI 帧头编解码，含起始字节、长度域与控制域。
 * 所有函数均为无状态实现，可重入。
 * @{
 */

/** @brief 起始字节固定值 */
#define APCI_START_BYTE 0x68

/**
 * @brief       编码 APCI 帧头
 *
 * @param[in]   {uint8_t} ctrl 控制域第 1 字节
 * @param[out]  {uint8_t*} out 输出缓冲区，需至少 6 字节
 * @return      none
 * @todo        none
 * @details     none
 */
void apci_encode_header(uint8_t ctrl, uint8_t* out);

/**
 * @}
 *
 */
```

注意 `@defgroup` 的组 ID（`iec104_apci`）与显示名（`APCI 层`）分开写；同名的 `@defgroup` 在整个工程里只能出现一次。

---

## 7. 成员尾随注释 `/**< */`

```c
typedef enum {
    APCI_START  = 0x68,     /**< 起始字节固定值 */
    APCI_CTRL_I = 0x00,     /**< I 帧控制域偏移 */
    APCI_CTRL_S = 0x01      /**< S 帧控制域偏移 */
} ApciByte;

struct LinkStat {
    uint32_t txCount;       /**< 已发送 I 帧数 */
    uint32_t rxCount;       /**< 已接收 I 帧数 */
    uint16_t vs;            /**< 发送序号 */
    uint16_t vr;            /**< 接收序号 */
};
```

`/**<` 表示"注释前一个元素"，必须与成员同行；`/**` 单独一行则是给**后一个**元素用的。

---

## 8. Qt 工程常见形态

信号：

```c
signals:
    /**
     * @brief       收到完整 APDU 后发出
     *
     * @param[in]   {const QByteArray&} apdu 完整 APDU 字节流
     * @return      none
     * @todo        none
     * @details     由 Qt 元对象系统自动连接，勿手动调用。
     */
    void apduReceived(const QByteArray& apdu);
```

槽 / 成员函数（类内缩进 4 空格，注释块同步缩进）：

```c
    /**
     * @brief       从串口缓冲区取走一帧并解析
     *
     * @param[in]   {const QByteArray&} data 新到达的字节流
     * @return      none
     * @todo        none
     * @details     内部维护半帧缓存，跨调用保留残余数据。
     */
    void onReadyRead(const QByteArray& data);
```

---

## 9. 常见错误对照

| 错误写法 | 问题 | 正确写法 |
|----------|------|----------|
| ` * @brief   $0` | 占位符未替换 | ` * @brief   解析一个 APDU 帧` |
| ` * @file    $TM_FILENAME` | 占位符未替换 | ` * @file    frame_decoder.h` |
| ` * @warning 无` | 空值未按规范写 | ` * @warning none` |
| ` * @param int len` | 缺方向、缺大括号 | ` * @param[in]   {int} len 长度（字节）` |
| ` * @return` 留空 | 空标签 | ` * @return  none` |
| `/* ... */` | 单星号不是 Doxygen 块 | `/** ... */` |
| `///` 混用 | 与工程模板不一致 | 统一用 `/** */` 块 |
| 文件头放在 `#include` 之后 | 放置位置错误 | 移到首个 `#ifndef` 之前 |
