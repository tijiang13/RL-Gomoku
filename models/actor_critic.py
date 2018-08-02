import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.distributions import Categorical


class PolicyNet(nn.Module):
    def __init__(self, num_actions):
        super().__init__()
        self.fc1 = nn.Linear(num_actions, 100)
        self.policy_head = nn.Linear(100, num_actions)
        self.value_head = nn.Linear(100, 1)

        self.log_probs = []
        self.values = []

    def forward(self, x):
        x = F.relu(self.fc1(x))
        policy = F.softmax(self.policy_head(x), dim=-1)
        value = self.value_head(x)
        return policy, value


def build_ctrl_fn(net):
    def ctrl_fn(state):
        state_feats = torch.from_numpy(state.board.flatten()).float().unsqueeze(0)
        probs, value = net(state_feats)
        mask = torch.zeros_like(probs).index_fill_(1, torch.from_numpy(state.valid_actions), 1)
        probs = probs * mask
        m = Categorical(probs)
        action = m.sample()

        net.log_probs.append(m.log_prob(action))
        net.values.append(value)
        return action.item()

    return ctrl_fn



def train(env, episodes, gamma=0.9):
    num_actions = env._board_size ** 2
    nets = [PolicyNet(num_actions), PolicyNet(num_actions)]
    optimizers = [optim.Adam(net.parameters()) for net in nets]
    ctrl_fns = [build_ctrl_fn(net) for net in nets]

    for episode in range(episodes):
        state = env.reset()
        rewards = []

        done = False
        while not done:
            action = ctrl_fns[state.cur_player](state)
            state, reward, done, _ = env.step(action)
            rewards.append(reward)

        rewards = np.array(rewards)
        rewards[:-1] -= rewards[1:]

        rewards = [rewards[0::2], rewards[1::2]]
        for i, (net, optimizer) in enumerate(zip(nets, optimizers)):
            Rs, R = [], 0
            for r in reversed(rewards[i]):
                R = gamma * R + r
                Rs.insert(0, R)
            Rs = torch.tensor(Rs)
            Rs = (Rs - Rs.mean()) / (Rs.std() + 1e-3)

            policy_loss = []
            value_loss = []
            for t, (R, value) in enumerate(zip(Rs, net.values)):
                policy_loss.append(-net.log_probs[t] * (R - value.item()))
                value_loss.append(F.smooth_l1_loss(value, torch.tensor([[R]])))
            policy_loss = torch.stack(policy_loss).sum()
            value_loss = torch.stack(value_loss).sum()
            loss = policy_loss + value_loss

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            del net.log_probs[:]
            del net.values[:]
        del rewards

    return ctrl_fns

