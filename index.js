const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');

const app = express();
app.use(bodyParser.json());

const GUPSHUP_API_URL = 'https://api.gupshup.io/sm/api/v1/msg';
const API_KEY = 'sk_7b388ebe42994a0585db4a36584741cd';
const BOT_PHONE_NUMBER = '917834811114';

app.get('/', (req, res) => {
    res.send('Bot Orcamento Pessoal está rodando!');
});

app.post('/webhook', async (req, res) => {
    const incomingMessage = req.body;
    console.log('Mensagem recebida:', incomingMessage);

    if (incomingMessage.type === 'message' && incomingMessage.payload?.payload?.text) {
        const userPhone = incomingMessage.payload?.sender?.phone;
        const userName = incomingMessage.payload?.sender?.name;
        const userMessage = incomingMessage.payload?.payload?.text;

        const replyMessage = `Olá ${userName}! Você disse: "${userMessage}". Como posso te ajudar hoje?`;

        try {
            await axios.post(GUPSHUP_API_URL, {
                channel: 'whatsapp',
                source: BOT_PHONE_NUMBER,
                destination: userPhone,
                message: {
                    type: 'text',
                    text: replyMessage
                },
                src_name: 'OrcamentoPessoalBot'
            }, {
                headers: {
                    'Content-Type': 'application/json',
                    'apikey': API_KEY
                }
            });

            console.log('Mensagem enviada com sucesso!');
        } catch (error) {
            console.error('Erro ao enviar mensagem:', error.response?.data || error.message);
        }
    }

    res.sendStatus(200);
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Servidor rodando na porta ${PORT}`);
});
