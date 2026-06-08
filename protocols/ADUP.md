# 3. Adaptive Downward/Upward Protocol

[cite_start]In this paper, we consider upward and downward routing in mobile scenarios[cite: 115]. [cite_start]In these scenarios, we suppose that all nodes are free to move except the sink node[cite: 116]. [cite_start]In upward routing, every node periodically generates data that are destined to the sink at a constant rate[cite: 117]. [cite_start]Before sending packets, each node selects a next-hop from its neighbors based on RRD+[cite: 118]. [cite_start]RRD+ helps to cope with the frequent-topology-changes problem in mobility[cite: 119]. 

[cite_start]In downward routing, the sink periodically sends command packets to nodes[cite: 120]. [cite_start]Due to the movement of nodes, routes from the sink to sensor nodes do not stay the same[cite: 121]. [cite_start]If route information cannot be updated on time, packets may be lost[cite: 122]. [cite_start]In what follows, we present our method, which is an extension of RRD+ that copes with downward routing in mobility[cite: 123].

## 3.1. Overview of RRD+ Mechanism

[cite_start]We integrated downward routing in RRD+, which was originally designed for upward routing[cite: 127]. [cite_start]RRD+ is a routing mechanism that can be used by hierarchical routing protocols to cope with mobility in convergecast data-collection scenarios[cite: 128]. [cite_start]It is based on link quality monitoring and Rank value updating to better adapt to movement, and makes fast decisions on selecting next-hop neighbors[cite: 129]. [cite_start]Moreover, RRD+ supports a dynamic management of control messages in order to reduce the overhead in the network[cite: 130]. [cite_start]In what follows, we describe the different aspects of RRD+[cite: 131].

### 3.1.1. Movement Direction Monitoring
[cite_start]RRD+ uses variation of Received Signal Strength Indicator (RSSI) to monitor movement direction[cite: 133]. [cite_start]Nodes obtain RSSI values from acknowledgement (ACK) messages and control messages[cite: 134]. [cite_start]A node manages two RSSI values for each parent node, Old RSSI value and New RSSI value[cite: 135]. [cite_start]Old RSSI is retrieved from the previous ACK or control message, and New RSSI value is obtained from currently received ACK or control message[cite: 136]. [cite_start]According to the variation of New RSSI value with regards to Old RSSI value, RRD+ estimates and monitors the movement direction of nodes[cite: 137]. [cite_start]When a New RSSI value is lower than an Old RSSI value, RRD+ considers that the node is moving away from its parent node[cite: 138]. [cite_start]Otherwise, RRD+ considers that the node is moving closer to its parent node[cite: 139].

### 3.1.2. Link-Quality Monitoring
[cite_start]Due to unpredictable path attenuations, RSSI values might vary even when neither node moves[cite: 141]. [cite_start]In order to take this phenomenon into account, we introduce two RSSI thresholds: Safety Threshold and Hysteresis Threshold, where the Safety Threshold is larger than the Hysteresis Threshold, as shown in Figure 1[cite: 142]. [cite_start]We used a dotted line for Safety Threshold, and a dashed line for Hysteresis Threshold[cite: 142]. [cite_start]Note that, due to the nature of wireless-signal propagation, in reality both RSSI thresholds and transmission range are most likely to look like a cloud and in our simulation model we used a probabilistic propagation model to take into account coverage-zone instability[cite: 143]. 

[cite_start]*(Figure 1 shows Node P as the parent node of nodes A, B, and C[cite: 153]. Node A is in the Safety zone of node P[cite: 153]. Node B is in the Hysteresis zone of node P[cite: 153]. Node C is in the Danger zone of node P[cite: 153]. The Safety Threshold of P is a dotted line, Hysteresis Threshold of P is a dashed line, and the Transmission range of P is a solid line [cite: 151, 152])*

[cite_start]When New RSSI is higher than or equal to Safety Threshold, the node is considered to be in the Safety zone of its parent node, and it has good link quality with it; this is the case of node A in Figure 1[cite: 156, 157]. [cite_start]When New RSSI is smaller than Safety Threshold but higher than Hysteresis Threshold, which is the case of node B in Figure 1, we need to first detect movement direction and then consider whether to stop using the link or not[cite: 157]. [cite_start]In order to reduce coverage-zone variation influence, we add a hysteresis value to Old RSSI when comparing it to New RSSI[cite: 158]. [cite_start]When New RSSI is smaller than Hysteresis Threshold, which is the case of node C in Figure 1, only New RSSI and Old RSSI are used to estimate direction without using hysteresis[cite: 159].

### 3.1.3. Rank Updating
[cite_start]Rank mechanism, which is proposed by RPL, is also an important part of RRD+[cite: 161]. [cite_start]The Rank of a node is a value that defines the position of the node with respect to the sink in terms of routing metrics[cite: 162]. [cite_start]The Rank of the sink node is ROOT_RANK and Min HopRankIncrease is the minimum increase of the Rank between a node and any of its parent nodes[cite: 163]. [cite_start]The rank value is proportional to the increase of the metric contained in control messages; therefore, the Rank of a node is calculated as shown in Equation (1)[cite: 164, 165].

$$Rank = ROOT\_RANK + a \times Min\_HopRankIncrease$$

[cite_start]where $a$ is a value included in control messages that come from lower rank nodes[cite: 167]. 

[cite_start]A node is not allowed to send data packets to neighbors with higher or equal Ranks, which is an effective way to avoid loops in the network[cite: 169]. [cite_start]In mobility scenarios, the position of a node frequently changes[cite: 170]. [cite_start]The original Rank mechanism does not offer methods to update the Rank in a timely manner[cite: 171]. [cite_start]This causes loops when a parent node becomes a descendant node[cite: 172]. [cite_start]RRD+ monitors link existence and movement direction to allow nodes to update their Ranks in a timely manner[cite: 173]. [cite_start]The goal is to update the Rank of a node when it is about to lose its link with its current parent node based on the link quality-monitoring mechanism[cite: 174].

### 3.1.4. Dynamic Control Message Management
[cite_start]In mobile scenarios, propagation of control messages needs to be more frequent in order to adapt to topology changes[cite: 176]. [cite_start]Maintaining up-to-date information about topology causes high overhead[cite: 177]. [cite_start]In our case, similarly to RPL, control messages are broadcast by the sink node and propagated by other nodes until they reach leaf nodes[cite: 177]. [cite_start]In RRD+, we designed a dynamic control message management according to Rank values in order to reduce overhead[cite: 178]. [cite_start]Nodes that are closer to the sink should send control messages more frequently and the frequency is reduced for nodes with higher Ranks[cite: 179]. [cite_start]Control messages coming from lower Rank nodes will help more nodes find parent nodes[cite: 180]. [cite_start]When a node changes its Rank value, it automatically adapts its control message interval[cite: 181]. [cite_start]The control message interval calculation is shown in Equation (2)[cite: 182].

$$Interval = Base\_interval + Rank \times Time\_unit$$

[cite_start]where Interval dynamically changes due to the change of Rank of nodes in mobility[cite: 186]. [cite_start]Base_interval is the smallest Interval[cite: 186]. [cite_start]Rank stands for the current Rank value of the node[cite: 187]. [cite_start]Time_unit is the incremental step in the control message frequency[cite: 187]. [cite_start]Base_interval and Time_unit can be fixed according to the application needs[cite: 188]. [cite_start]High densities and high speeds would require smaller values of Interval[cite: 189].

## 3.2. Dynamic Next-Hop Table

[cite_start]In RRD+, all neighbors with lower Ranks form a set that we call a parent set[cite: 191]. [cite_start]In a data-collection process, before sending a packet, a node needs to select a next-hop from its parents set[cite: 192]. [cite_start]In ADUP, the ID of this next-hop is included into data packets and sent to the sink[cite: 193]. [cite_start]Instead of storing the entire addresses of next-hop nodes in data packets, we only use 1 byte to store the ID of the next-hop node of the source node[cite: 194]. [cite_start]Due to the fact that the upper limit value of 1 byte is 255, the maximum number of nodes in the network cannot exceed 255[cite: 194, 198]. [cite_start]Figure 2 shows the fields of upward data packets[cite: 198]. 

[cite_start]**Figure 2. Fields of upward data packets.** [cite: 204, 205]
[cite_start]*(The total size is 128 Bytes [cite: 204])*
| Data | Sender address | Receiver address | ID of next-hop | Packet Id | Idle |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 0-29 Bytes | 30-31 Bytes | 32-33 Bytes | 34 Byte | 35-36 Bytes | 37-127 Bytes |

[cite_start]When the sink receives data packets, it builds a next-hop table as shown in Figure 3[cite: 199]. [cite_start]The first column of this table stands for the ID of nodes, except the sink, in the network[cite: 199]. [cite_start]We consider that there are $n$ nodes and one sink in the topology[cite: 200]. [cite_start]We define the ID of each node as $ID_i \in \{ID_0, ID_1, ID_2, ..., ID_n\}$, where $ID_0$ stands for the ID of sink[cite: 201]. [cite_start]The second column stands for the ID of best next-hop for each node referred to as $N(ID_i)$[cite: 202]. [cite_start]Note that $N(X) \in \{ID_0, ID_1, ID_2, ..., ID_n\}$ and $X \in \{ID_1, ID_2, ..., ID_n\}$[cite: 203].

[cite_start]**Figure 3. Dynamic next-hop table of the sink node.** [cite: 206, 207, 208, 209, 210, 211, 212, 213, 214]
| ID | Nexthop |
| :---: | :---: |
| $ID_1$ | $N(ID_1)$ |
| $ID_2$ | $N(ID_2)$ |
| ... | ... |
| $ID_n$ | $N(ID_n)$ |

[cite_start]RRD+ updates the Rank value of each node according to link quality and movement direction[cite: 215]. [cite_start]Nodes in a parents set are automatically removed or added based on the variation of Rank values[cite: 216]. [cite_start]Thus, the next-hop of each node also dynamically changes according to movement[cite: 217]. [cite_start]Due to the fact that each node periodically sends packets to the sink, the next-hop table periodically adapts to mobility[cite: 218].

## 3.3. Route Building in Downward Routing

[cite_start]In order to reach the destination through multiple hops, the sink needs to build a route before sending a packet[cite: 220]. [cite_start]Algorithm 1 depicts the route-building process[cite: 221]. [cite_start]We use $ID_d$ to stand for the ID of the destination node which is put into the route first[cite: 221]. [cite_start]The sink extracts the preferred next-hop of $ID_d$ from the dynamic next-hop table[cite: 222]. [cite_start]If $N(ID_d)$ equals $ID_0$ this means that the sink can directly reach node $ID_d$, and the building process immediately stops[cite: 223]. [cite_start]In case $N(ID_d)$ is not $ID_0$, the sink continues the route-building process[cite: 224]. [cite_start]For any entry in the first column of dynamic next-hop table, the entry $ID_i$ that equals $N(ID_d)$ is put into the route, and its next-hop $N(ID_i)$ needs to be compared to $ID_0$[cite: 225]. [cite_start]The building process stops when the next-hop of item $ID_i$ is $ID_0$[cite: 226]. [cite_start]The building process of a route is done from the destination to the sink, the route we get is in reverse order, and it is thus reversed before it is used as a path[cite: 227]. 

[cite_start]Figure 4 shows how Algorithm 1 works[cite: 228]. [cite_start]$ID_d$ is put into the route first[cite: 228]. [cite_start]During this process, the numbers of $ID_i$ are put in the route until the next-hop of $ID_x$ is found to be $ID_0$[cite: 229]. [cite_start]At the end, the route needs to be reversed[cite: 230].

[cite_start]**Algorithm 1: Route building.** [cite: 249, 250, 251, 252, 253, 254, 255, 256, 257, 258, 259, 260, 261, 262, 263, 264]
```text
Input: ID_d
Output: Route
begin
    Put ID_d in the Route;
    Nexthop = N(ID_d);
    while Nexthop does not equal to ID_0 do
        for each item i in ID_i do
            if ID_i = Nexthop then
                Nexthop = N(ID_i);
                Put ID_i in the Route;
            end
        end
    end
    Reverse(Route);
end

We consider that there are $m$ nodes in the route. Before sending a data packet, the sink needs to store the IDs of these nodes in the data packet as shown in Figure 5. Every time the data packet is relayed, the route offset will be increased to help relay nodes to find the next-hop within $m$ bytes until reaching the destination.

**Figure 5. Fields of downward data packets.**
*(The total size is 128 Bytes)*

| Data | Sender address | Receiver address | Route offset | Route path | Packet Id | Idle |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0-29 Bytes | 30-31 Bytes | 32-33 Bytes | 34 Byte | $35-(35+m)$ Bytes | $35+m+1$ Bytes | $35+m+2-127$ Bytes |

*Details of the $m$ Bytes Route path:*
* *Byte 35:* $ID_0$
* *...*
* *Byte $35+(m-1)$:* $ID_i$
* *Byte $35+m$:* $ID_d$
* *(The Route offset points to the current ID in this path)*