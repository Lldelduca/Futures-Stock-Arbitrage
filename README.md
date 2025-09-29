# Arbitrage Trading Strategies – Financial Derivatives Assignment  

This repository contains the code and final report for **Assignment 1: Arbitrage Trading Strategies** in the course *Financial Derivatives (FEM21011)*. The assignment required developing automated trading strategies in **Python** for the **Optibook virtual exchange**, exploiting mispricings between related financial instruments while managing execution risk, hedging, and exchange-imposed limits.  

---

## 1. Overview  

The project explores arbitrage trading in two main contexts:  

1. **Dual listing arbitrage**: two listings of the same stock, each with its own order book.  
2. **Stock–futures arbitrage**: a stock and its futures contracts, linked through cost-of-carry pricing.  

All strategies are executed algorithmically, and their performance is evaluated based on **PnL**, **volatility**, and **Sharpe ratios**.  

---

## 2. Dual Listing Arbitrage  

A stock and its dual listing represent identical ownership rights. In an efficient market their prices should be equal, yet temporary divergences occur. Arbitrage exploits this by buying the undervalued listing and selling the overvalued one.  

### 2.1 Midpoint Rule  

Let  

$$ m_i = \frac{a_i + b_i}{2}, \quad s_i = a_i - b_i $$  

be the midpoint and spread of market \( i \in \{S,D\} \), where \(a_i\) is the best ask and \(b_i\) is the best bid.  

Arbitrage exists when the difference between midpoints exceeds half-spreads and transaction costs:  

$$ 
m_S - m_D > \frac{s_S + s_D}{2} + (c_S + c_D) 
\quad \Longleftrightarrow \quad b_S - a_D > c_S + c_D 
$$  

or symmetrically,  

$$ 
m_D - m_S > \frac{s_S + s_D}{2} + (c_S + c_D) 
\quad \Longleftrightarrow \quad b_D - a_S > c_S + c_D 
$$  

The algorithm implements this by monitoring both order books. If \(b_S > a_D\), it buys the dual listing at \(a_D\) and sells the stock at \(b_S\). If the reverse inequality holds, the trade is reversed.  

### 2.2 Execution and Hedging (A2)  

The baseline dual-listing strategy is exposed to **delta risk**: if the stock moves significantly while holding an uncovered dual position, the PnL can deteriorate.  

To mitigate this, the algorithm implements **delta-hedging**:  
- When a position is opened in the dual, an offsetting position is opened in the stock.  
- This ensures that the combined exposure is close to zero:  

$$
p = p_D + p_S \approx 0
$$  

where \(p_D\) is the position in the dual and \(p_S\) is the position in the stock.  

If the hedge fails (for example due to lack of liquidity), the algorithm retries in the next iteration. This reduces volatility, though at the cost of slightly lower average PnL.  

Execution risk is handled by first verifying fills in the dual, and only then sending hedge orders in the stock. Additionally, the algorithm can place more aggressive orders (sacrificing a small profit margin) to improve the probability of execution.  

---

## 3. Stock–Futures Arbitrage  

The fair relationship between spot and futures prices is given by the **cost-of-carry model**:  

$$
F = S \cdot e^{r \tau}
$$  

where \(S\) is the stock price, \(F\) is the futures price, \(r\) is the continuously compounded risk-free rate, and \(\tau\) is time to maturity in years.  

To compare a futures order book with the stock, the algorithm constructs a **synthetic stock price**:  

$$
\tilde{S}_{bid} = b_F \cdot e^{-r \tau}, 
\quad 
\tilde{S}_{ask} = a_F \cdot e^{-r \tau}
$$  

An arbitrage exists when:  

$$
\tilde{S}_{bid} - a_S > c_F + c_S 
\quad \Rightarrow \quad \text{Sell futures, buy stock}
$$  

or  

$$
b_S - \tilde{S}_{ask} > c_F + c_S 
\quad \Rightarrow \quad \text{Buy futures, sell stock}
$$  

### 3.1 Delta Hedging  

A futures contract has sensitivity (delta):  

$$
\Delta = \frac{\partial F}{\partial S} = e^{r \tau}
$$  

Thus, for \(p_F\) futures contracts and \(p_S\) stock shares, the portfolio delta is:  

$$
\Delta_{tot} = p_F \cdot e^{r \tau} + p_S
$$  

The algorithm enforces near-delta neutrality:  

$$
\Delta_{tot} \in \left(-\tfrac{1}{2}, \tfrac{1}{2}\right]
$$  

by dynamically adjusting stock positions whenever futures trades occur.  

### 3.2 Risk Management and Hedging Strategies (B2)  

When trading futures and stocks, exchange rules limit each position to ±100 lots. Managing hedging under these constraints requires specific strategies. Two approaches are implemented:  

1. **Naive hedge**: execute the full hedge implied by \(\Delta\), truncating only when position limits are hit. This captures more spread opportunities but may leave residual risk.  
2. **Δ-minimizing hedge**: pre-adjust order sizes so that the final residual delta remains within tolerance, while staying inside position limits. This reduces risk at the cost of smaller trade sizes.  

Both strategies are implemented and compared. The naive approach yields higher gross PnL but leaves larger exposures when limits bind. The Δ-minimizing hedge provides tighter control of risk and higher Sharpe ratios.  

### 3.3 Variable Volume Strategy  

Initially, trades are restricted to one lot per order. Later, the algorithm is extended to trade multiple lots per opportunity, capped by the exchange position limit (\(\pm 100\)). This increases trading frequency and cumulative PnL, though volatility rises as well.  

---

## 4. Futures–Futures Arbitrage (B3)  

For two futures \(F_1\) and \(F_2\) on the same stock with maturities \(\tau_1\) and \(\tau_2\):  

$$
e^{-r \tau_1} F_1 = e^{-r \tau_2} F_2 = S
$$  

Any deviation implies an arbitrage opportunity. The algorithm detects when:  

$$
e^{-r \tau_1} b_{F1} > e^{-r \tau_2} a_{F2}
\quad \text{or} \quad 
e^{-r \tau_2} b_{F2} > e^{-r \tau_1} a_{F1}
$$  

and executes simultaneous long–short trades across the two futures.  

### 4.1 Hedging with Stock  

Residual deltas from the two-futures spread are hedged with the stock:  

$$
\Delta_{tot} = p_{F1} \cdot e^{r \tau_1} + p_{F2} \cdot e^{r \tau_2} + p_S
$$  

The hedge volume is:  

$$
p_S^{hedge} = -\text{round}(\Delta_{tot})
$$  

This ensures the combined position remains nearly delta-neutral.  

### 4.2 Flexible Hedging  

Instead of always hedging with the stock, the algorithm dynamically chooses whether to hedge with the stock or the other future, depending on which provides the better execution price. This flexibility improves profitability and Sharpe ratios, as it allows hedging at the most competitive market quotes.  

---

## 5. Implementation Details  

The algorithms are implemented in Python using the Optibook API. Key features include:  

- Connection to the exchange via `Exchange()` object.  
- Continuous polling of order books and positions.  
- Immediate-or-cancel (IOC) orders to avoid leaving stale liquidity.  
- Position management with automatic hedging.  
- Respect of Optibook limits: maximum ±100 positions per instrument, maximum 200 outstanding orders, and no more than 25 updates per second.  

